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


TOPICS = {
    "economy": "경제·증시",
    "semis_ai": "반도체·AI",
    "politics": "정치·안보",
    "international": "국제",
    "industry": "산업",
    "society": "사회",
    "entertainment_sports": "연예·스포츠",
    "incidents": "사건·사고",
    "lifestyle_culture": "생활·문화",
    "science": "과학",
}


# ---------- config.yaml ----------

class Window(Strict):
    # 시간창 = 직전 발행 호의 끝 ~ 이번 호의 end. 직전 호가 없으면 24시간, 발행을 오래 놓쳐도 max_hours 까지만 거슬러 간다
    end: str
    max_hours: int = Field(default=72, ge=24, le=168)

    @field_validator("end")
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
    # driven: 관심도 덕분에 들어온 기사(관심도를 빼고 골랐다면 빠졌을 기사)만 상한에 셈 (2026-10-16 사용자 결정)
    # topic: 관심 분야 기사 전체를 상한에 셈
    interest_cap_mode: Literal["driven", "topic"] = "driven"

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


SectionId = Literal["front", "politics", "economy", "international", "interest", "compare", "briefs", "opinion", "guide"]


class Section(Strict):
    id: SectionId
    title: str = Field(min_length=1)
    max_articles: int = Field(ge=0)


class Clustering(Strict):
    model: str
    similarity_threshold: float = Field(gt=0, lt=1)
    linkage: Literal["average", "complete", "single"] = "average"
    lexical_weight: float = Field(default=0.5, ge=0, le=1)  # 같은 언어 쌍에서 어휘 겹침 비중
    cross_lang_csls_min: float = Field(default=0.06, gt=-1, lt=1)  # 다른 언어 쌍이 묶이는 CSLS 점수
    csls_k: int = Field(default=10, ge=1, le=50)                  # CSLS 의 이웃 수
    csls_min_by_lang: dict[Literal["ko", "en", "ja", "zh", "ar"], float] = Field(default_factory=dict)


class Importance(Strict):
    topic_weights: dict[str, float]          # 분야별 기본 중요도
    keywords: list[str]                      # 핵심 키워드 (제목에 나오면 가산)
    keyword_bonus: float = Field(ge=0, le=1)

    @field_validator("topic_weights")
    @classmethod
    def _all_topics(cls, v: dict[str, float]) -> dict[str, float]:
        missing = sorted(set(TOPICS) - set(v))
        unknown = sorted(set(v) - set(TOPICS))
        if missing or unknown:
            raise ValueError(f"분야 가중치 누락 {missing}, 알 수 없는 분야 {unknown}")
        if any(w < 0 for w in v.values()):
            raise ValueError("분야 가중치는 음수일 수 없음")
        return v


class Photos(Strict):
    front: int = Field(ge=0, le=5)        # 1면 사진 수 상한
    per_section: int = Field(ge=0, le=3)  # 섹션당 사진 수 상한


class Llm(Strict):
    enabled: bool
    model: str
    max_calls_per_day: int = Field(ge=0, le=60)
    timeout_sec: int = Field(gt=0, le=600)
    # 본문 기반 이슈 분석 (S14, D13·D15): 지면 상위 묶음만, 여러 묶음을 한 번에
    analysis_model: str = "sonnet"
    analysis_issues: int = Field(default=40, ge=0, le=60)
    analysis_batch: int = Field(default=5, ge=1, le=10)
    analysis_timeout_sec: int = Field(default=300, gt=0, le=900)


class Config(Strict):
    timezone: str
    window: Window
    publish_time: str
    weights: Weights
    editing: Editing
    sections: list[Section] = Field(min_length=1)
    clustering: Clustering
    importance: Importance
    photos: Photos
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

Lean = Literal["보수", "중도", "진보", "경제지", "통신·공영", "관영"]
MediaType = Literal["종합지", "경제지", "방송", "통신", "국제"]


class Feed(Strict):
    section: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://")
    main: bool = False  # 매체 메인(톱) 피드 여부 — 주목도 계산에 사용
    # rss: 매체 공식 피드 / google_news: 공식 피드가 없어 Google 뉴스의 매체 한정 검색 피드로 대체(리드 없음)
    kind: Literal["rss", "google_news"] = "rss"
    # feed: 피드의 발행 시각 사용 / page_meta: 피드에 시각이 없어 기사 페이지 <meta> 의 발행 시각을 읽음
    date_source: Literal["feed", "page_meta"] = "feed"
    # 이 문자열이 제목에 있는 항목만 받는다 (예: Google 뉴스 검색 피드에서 "[사설]"만)
    title_must: str | None = None


class Source(Strict):
    name: str = Field(min_length=1)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    lean: Lean
    type: MediaType
    weight: float = Field(gt=0, le=5)
    paywall: bool
    enabled: bool
    feeds: list[Feed]
    # 받을 기사 언어(ko/en/ja/zh/ar). 비우면 전부. 예: 조선일보 피드에는 일본어판 기사가 섞여 들어온다
    langs: list[Literal["ko", "en", "ja", "zh", "ar"]] = Field(default_factory=list)

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


COMPARE_TOPICS = {
    "diplomacy_security": "외교·안보",
    "economic_policy": "경제 정책",
    "domestic_politics": "국내 정치",
    "tech_regulation": "테크·규제",
}


class ForeignDisplay(Strict):
    english: Literal["original", "original_with_ko_summary", "translated_title"]
    other: Literal["original", "original_with_ko_summary", "translated_title"]


class Interests(Strict):
    topics: dict[str, float]
    keywords: list[str]
    less: list[str]
    default_weight: float = Field(ge=0)
    less_weight: float = Field(ge=0)
    keyword_boost: float = Field(ge=0)
    daily_articles: int = Field(gt=0, le=200)
    compare_topics: list[str]
    foreign_display: ForeignDisplay

    @field_validator("topics")
    @classmethod
    def _topics(cls, v: dict[str, float]) -> dict[str, float]:
        unknown = sorted(set(v) - set(TOPICS))
        if unknown:
            raise ValueError(f"알 수 없는 분야: {unknown} (가능: {sorted(TOPICS)})")
        bad = {k: w for k, w in v.items() if w < 0}
        if bad:
            raise ValueError(f"관심 가중치는 음수일 수 없음: {bad}")
        return v

    @field_validator("less")
    @classmethod
    def _less(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(TOPICS))
        if unknown:
            raise ValueError(f"알 수 없는 분야: {unknown}")
        return v

    @field_validator("compare_topics")
    @classmethod
    def _compare(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(COMPARE_TOPICS))
        if unknown:
            raise ValueError(f"알 수 없는 비교 유형: {unknown} (가능: {sorted(COMPARE_TOPICS)})")
        return v

    @model_validator(mode="after")
    def _no_overlap(self) -> "Interests":
        both = sorted(set(self.topics) & set(self.less))
        if both:
            raise ValueError(f"관심 분야와 덜 볼 분야에 동시에 있음: {both}")
        return self


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
