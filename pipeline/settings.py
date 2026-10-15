"""config.yaml · sources.yaml · interests.yaml 읽기와 검증.

잘못된 값은 조용히 넘기지 않고 어느 파일의 어느 항목이 왜 틀렸는지 알려 주며 멈춘다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ROOT = Path(__file__).resolve().parent.parent

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class Strict(BaseModel):
    # 오타 난 키를 모르는 채 넘기지 않도록 정의되지 않은 키는 거부
    model_config = ConfigDict(extra="forbid")


# ---------- config.yaml ----------

class Window(Strict):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError(f"시각은 HH:MM 형식이어야 함: {v!r}")
        return v


class Weights(Strict):
    attention: float = Field(ge=0)
    importance: float = Field(ge=0)
    continuity: float = Field(ge=0)
    interest: float = Field(ge=0)

    @model_validator(mode="after")
    def _nonzero(self) -> "Weights":
        if self.attention + self.importance + self.continuity + self.interest <= 0:
            raise ValueError("가중치 합이 0보다 커야 함")
        return self


class Editing(Strict):
    total_articles: int = Field(gt=0, le=200)
    diversity_ratio: float = Field(ge=0, le=1)
    interest_cap: float = Field(ge=0, le=1)
    continuity_min_days: int = Field(ge=1)
    history_days: int = Field(ge=1, le=60)

    @model_validator(mode="after")
    def _ratios(self) -> "Editing":
        # 다양성 슬롯과 관심 슬롯은 겹치지 않으므로 합이 1을 넘을 수 없다
        if self.diversity_ratio + self.interest_cap > 1:
            raise ValueError(
                f"diversity_ratio({self.diversity_ratio}) + interest_cap({self.interest_cap}) 가 1을 넘음"
            )
        if self.continuity_min_days > self.history_days:
            raise ValueError("continuity_min_days 가 history_days 보다 클 수 없음")
        return self


SectionId = Literal["front", "politics", "economy", "international", "interest", "compare", "briefs", "guide"]


class Section(Strict):
    id: SectionId
    title: str = Field(min_length=1)
    max_articles: int = Field(ge=0)


class Clustering(Strict):
    model: str
    similarity_threshold: float = Field(gt=0, lt=1)


class Llm(Strict):
    enabled: bool
    model: str
    max_issues_per_day: int = Field(ge=0, le=50)
    timeout_sec: int = Field(gt=0, le=600)


class Config(Strict):
    timezone: str
    window: Window
    publish_time: str
    weights: Weights
    editing: Editing
    sections: list[Section] = Field(min_length=1)
    clustering: Clustering
    llm: Llm

    @field_validator("publish_time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError(f"시각은 HH:MM 형식이어야 함: {v!r}")
        return v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"알 수 없는 시간대: {v!r}") from None
        return v

    @model_validator(mode="after")
    def _sections(self) -> "Config":
        ids = [s.id for s in self.sections]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"섹션 id 중복: {sorted(dup)}")
        if ids[0] != "front":
            raise ValueError("첫 섹션은 front(1면)여야 함")
        return self


# ---------- sources.yaml ----------

Lean = Literal["보수", "중도", "진보", "경제지", "통신·공영"]
MediaType = Literal["종합지", "경제지", "방송", "통신", "국제"]


class Feed(Strict):
    section: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://")
    main: bool = False  # 매체 메인(톱) 피드 여부 — 주목도 계산에 사용


class Source(Strict):
    name: str = Field(min_length=1)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    lean: Lean
    type: MediaType
    weight: float = Field(gt=0, le=5)
    paywall: bool
    enabled: bool
    feeds: list[Feed]

    @model_validator(mode="after")
    def _enabled_needs_feed(self) -> "Source":
        if self.enabled and not self.feeds:
            raise ValueError(f"{self.name}: enabled 인데 feeds 가 비어 있음")
        return self


class Sources(Strict):
    sources: list[Source] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> "Sources":
        names = [s.name for s in self.sources]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise ValueError(f"매체명 중복: {sorted(dup)}")
        return self


# ---------- interests.yaml ----------

class Interests(Strict):
    topics: dict[str, float]
    keywords: list[str]
    less: list[str]
    daily_articles: int = Field(gt=0, le=200)
    compare_topics: list[str]
    foreign_title: Literal["original", "translated"]

    @field_validator("topics")
    @classmethod
    def _nonneg(cls, v: dict[str, float]) -> dict[str, float]:
        bad = {k: w for k, w in v.items() if w < 0}
        if bad:
            raise ValueError(f"관심 가중치는 음수일 수 없음: {bad}")
        return v


# ---------- 읽기 ----------

class SettingsError(Exception):
    pass


def _load(path: Path, model: type[BaseModel]):
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SettingsError(f"{path.name}: 파일 없음") from None
    except yaml.YAMLError as e:
        raise SettingsError(f"{path.name}: YAML 문법 오류\n{e}") from None
    try:
        return model.model_validate(raw)
    except ValidationError as e:
        lines = [f"{path.name}: 설정 오류 {e.error_count()}건"]
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "(최상위)"
            lines.append(f"  - {loc}: {err['msg']}")
        raise SettingsError("\n".join(lines)) from None


def load_config(root: Path = ROOT) -> Config:
    return _load(root / "config.yaml", Config)


def load_sources(root: Path = ROOT) -> Sources:
    return _load(root / "sources.yaml", Sources)


def load_interests(root: Path = ROOT) -> Interests:
    return _load(root / "interests.yaml", Interests)
