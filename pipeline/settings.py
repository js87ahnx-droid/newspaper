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
    headline: float = Field(default=0.0, ge=0)        # 매체 머리기사 (S14b)
    front_headline: float = Field(default=0.0, ge=0)  # 1면 고를 때(주목도·중요도와 함께) 머리기사 비중

    @model_validator(mode="after")
    def _nonzero(self) -> "Weights":
        if self.attention + self.importance + self.continuity + self.interest + self.headline <= 0:
            raise ValueError("가중치 합이 0보다 커야 함")
        return self


class Editing(Strict):
    total_articles: int = Field(gt=0, le=200)
    diversity_ratio: float = Field(ge=0, le=1)
    interest_cap: float = Field(ge=0, le=1)
    continuity_min_days: int = Field(ge=1)
    # 연속 보장 상한 (S21c): 지면의 이 비율까지만. 10/18호는 30/60 이 연속 보장(매일 나오는 경기 결과 포함)이라 분야면이 비었음
    continuity_max_ratio: float = Field(default=1.0, ge=0, le=1)
    # 분야별 지면 상한 비율 (S21c). 예: {international: 0.4}. 1면 톱·다양성·연속 보장 기사도 셈에 들어간다
    topic_max_ratio: dict[str, float] = Field(default_factory=dict)

    @field_validator("topic_max_ratio")
    @classmethod
    def _topic_ratio(cls, v: dict[str, float]) -> dict[str, float]:
        bad = sorted(set(v) - set(TOPICS))
        if bad or any(not 0 < r <= 1 for r in v.values()):
            raise ValueError(f"topic_max_ratio: 알 수 없는 분야 {bad} 또는 0~1 밖의 비율")
        return v
    history_days: int = Field(ge=1, le=60)
    # driven: 관심도 덕분에 들어온 기사(관심도를 빼고 골랐다면 빠졌을 기사)만 상한에 셈 (2026-10-16 사용자 결정)
    # topic: 관심 분야 기사 전체를 상한에 셈
    interest_cap_mode: Literal["driven", "topic"] = "driven"
    # 예비 기사 (S15): 하루 분량 다음 순위 기사. 지면에 쪽이 남으면 단신으로 채운다 (같은 사건 합치기로 빈 자리도)
    reserve: int = Field(default=10, ge=0, le=300)

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


SectionId = Literal["front", "politics", "economy", "international", "society", "interest", "analysis", "compare", "briefs", "opinion", "guide"]


class Section(Strict):
    id: SectionId
    title: str = Field(min_length=1)
    max_articles: int = Field(ge=0)
    # 고정 쪽 수 (S15, D15). 이 쪽에 다 못 들어간 기사는 단신으로 내리고, 남긴 쪽은 단신이 쓴다. 0 = 따로 쪽을 두지 않음
    pages: int = Field(default=0, ge=0, le=8)


class Clustering(Strict):
    model: str
    similarity_threshold: float = Field(gt=0, lt=1)
    linkage: Literal["average", "complete", "single"] = "average"
    lexical_weight: float = Field(default=0.5, ge=0, le=1)  # 같은 언어 쌍에서 어휘 겹침 비중
    cross_lang_csls_min: float = Field(default=0.06, gt=-1, lt=1)  # 다른 언어 쌍이 묶이는 CSLS 점수
    csls_k: int = Field(default=10, ge=1, le=50)                  # CSLS 의 이웃 수
    csls_min_by_lang: dict[Literal["ko", "en", "ja", "zh", "ar", "fr", "de"], float] = Field(default_factory=dict)
    # 군집 문턱엔 못 미쳤지만 같은 사건으로 보이는 이웃 이슈 (편집에서 둘 다 싣지 않고 합친다, S14 평가)
    near_mean_min: float = Field(default=0.36, gt=0, lt=1)   # 두 이슈 기사 쌍 평균 유사도
    near_max_min: float = Field(default=0.55, gt=0, lt=1)    # 또는 (같은 언어끼리) 가장 가까운 기사 쌍


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
    front: int = Field(ge=0, le=6)        # 1면 사진 수 상한
    per_section: int = Field(ge=0, le=6)  # 섹션당 사진 수 상한


class Llm(Strict):
    enabled: bool
    model: str
    max_calls_per_day: int = Field(ge=0, le=60)
    timeout_sec: int = Field(gt=0, le=600)
    # 본문 기반 이슈 분석 (S14, D13·D15): 지면 상위 묶음만, 여러 묶음을 한 번에
    analysis_model: str = "sonnet"
    analysis_issues: int = Field(default=40, ge=0, le=100)
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
    # 라틴 문자 제목의 언어 (S20b): 문자 체계로는 영어와 못 가르므로 피드가 알려 준다. 비우면 en
    #   예: Le Monde 프랑스어판 fr, Spiegel 독일어판 de (같은 매체 영어판 피드는 비워 둔다)
    lang: Literal["fr", "de"] | None = None
    # 기사 주소가 이 정규식에 맞는 항목만 받는다 (S19e: Bloomberg 피드에 섞인 영상·오디오·뉴스레터를 거름)
    url_must: str | None = None
    # 제목이 이 정규식에 맞으면 버린다 (S20d: Google 뉴스 피드는 주소가 news.google.com 이라 url_must 가 듣지 않음 — 인민일보 판면·자료실 쪽)
    title_not: str | None = None

    @field_validator("url_must", "title_not")
    @classmethod
    def _regex(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                re.compile(v)
            except re.error as e:
                raise ValueError(f"정규식 오류: {e}") from None
        return v


class HeadlineSrc(Strict):
    """매체 머리기사를 얻는 곳 (S14b). 앞에서부터 시도해 처음 얻은 곳을 쓴다."""
    kind: Literal["naver_a1", "feed", "homepage"]
    press: str | None = Field(default=None, pattern=r"^\d{3}$")   # naver_a1: 네이버 언론사 번호
    url: str | None = Field(default=None, pattern=r"^https?://")    # feed·homepage

    @model_validator(mode="after")
    def _needs(self) -> "HeadlineSrc":
        if self.kind == "naver_a1" and not self.press:
            raise ValueError("naver_a1 은 press(네이버 언론사 번호)가 필요함")
        if self.kind != "naver_a1" and not self.url:
            raise ValueError(f"{self.kind} 는 url 이 필요함")
        return self


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
    langs: list[Literal["ko", "en", "ja", "zh", "ar", "fr", "de"]] = Field(default_factory=list)
    headline: list[HeadlineSrc] = Field(default_factory=list)  # 머리기사 (비우면 이 매체는 머리기사 가중 없음)
    # 기사 주소 도메인 — 원문 재배열 중계(worker/)의 허용목록. 하위 도메인 포함 (S17)
    site: list[str] = Field(default_factory=list)
    reader: bool = True   # false: 중계 서버로 못 여는 매체(봇 차단·유료 벽·자바스크립트) — 누르면 바로 원문으로

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
