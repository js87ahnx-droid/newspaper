"""2단계 정제: 누적 저장소에서 그날 호의 시간창(직전 호 이후 ~ 이번 호) 기사만 고르고 중복을 없앤다."""
from __future__ import annotations

import copy
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .collect import Article
from .settings import ROOT, Config, Sources
from .textutil import cap_lead, clean_lead, detect_analysis, detect_interview, detect_opinion, empty_title, title_key


DEFAULT_HISTORY = ROOT / "data" / "history"


def _end_at(d: date, cfg: Config) -> datetime:
    eh, em = map(int, cfg.window.end.split(":"))
    return datetime.combine(d, time(eh, em), ZoneInfo(cfg.timezone))


def previous_edition(edition: date, cfg: Config, history_dir: Path | None = None) -> date | None:
    """이 호보다 앞서 발행된 가장 최근 호 (연속성 기록 data/history/<날짜>.json 이 발행 기록을 겸한다)."""
    history_dir = DEFAULT_HISTORY if history_dir is None else history_dir
    days = cfg.window.max_hours // 24
    for back in range(1, days + 1):
        d = edition - timedelta(days=back)
        if (history_dir / f"{d.isoformat()}.json").exists():
            return d
    return None


def edition_window(edition: date, cfg: Config, history_dir: Path | None = None) -> tuple[datetime, datetime]:
    """호 날짜 → [직전 호의 end, 이 호의 end) 의 UTC 경계. 시작은 포함, 끝은 제외.
    직전 호가 없으면 24시간. 호와 호 사이가 빈틈·겹침 없이 이어진다."""
    end = _end_at(edition, cfg)
    prev = previous_edition(edition, cfg, history_dir)
    start = _end_at(prev, cfg) if prev else end - timedelta(hours=24)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def current_edition(now: datetime, cfg: Config) -> date:
    """지금 발행할 호: 가장 최근에 끝난 시간창의 날짜 (end 이후면 오늘, 이전이면 어제)."""
    local = now.astimezone(ZoneInfo(cfg.timezone))
    return local.date() if local >= _end_at(local.date(), cfg) else local.date() - timedelta(days=1)


def target_edition(now: datetime, cfg: Config) -> date:
    """수집·임베딩이 채워 갈 호: 아직 끝나지 않은 다음 시간창 (end 이후면 내일 호, 이전이면 오늘 호)."""
    return current_edition(now, cfg) + timedelta(days=1)


def prepare(
    store: dict[str, Article], edition: date, cfg: Config, sources: Sources, history_dir: Path | None = None
) -> tuple[list[Article], dict]:
    """sources 는 수집 뒤 바뀌었을 수 있으므로(성향 라벨·가중치 수정, 매체 끄기) 여기서 다시 적용한다."""
    start, end = edition_window(edition, cfg, history_dir)
    by_name = {s.name: s for s in sources.sources}
    names = frozenset(by_name)
    no_date = out_of_window = dup_title = disabled = wrong_lang = opinion = empty = 0
    in_window: list[Article] = []
    for a in store.values():
        src = by_name.get(a.source)
        if src is None or not src.enabled:
            disabled += 1
            continue
        if empty_title(a.title, names):   # 제목이 "- 중앙일보" 처럼 매체 이름·기호뿐 (S24d)
            empty += 1
            continue
        if src.langs and a.lang not in src.langs:
            wrong_lang += 1
            continue
        if not a.published:
            no_date += 1
            continue
        t = datetime.fromisoformat(a.published)
        if not (start <= t < end):
            out_of_window += 1
            continue
        if _is_opinion(a) or _side_kind(a):  # 논평·사설, 분석·해설(S22c), 지정 칼럼(S22d)은 뉴스 이슈·점수에 섞지 않는다
            opinion += 1
            continue
        a = copy.deepcopy(a)  # 누적 저장소의 원본은 건드리지 않는다
        a.country, a.lean, a.media_type, a.weight, a.paywall = src.country, src.lean, src.type, src.weight, src.paywall
        a.lead = cap_lead(a.lead)  # 누적분이 예전 상한으로 저장됐어도 지면에는 현재 상한만 나간다
        in_window.append(a)

    # 같은 매체가 주소만 다르게 같은 기사를 낸 경우(섹션별 주소, 모바일 주소 등): 제목 키로 합친다
    by_key: dict[tuple[str, str], Article] = {}
    for a in sorted(in_window, key=lambda a: a.published or ""):
        key = (a.source, title_key(a.title))
        kept = by_key.get(key)
        if kept is None:
            by_key[key] = a
            continue
        dup_title += 1
        for s in a.sections:
            if s not in kept.sections:
                kept.sections.append(s)
        kept.main = kept.main or a.main
        if len(a.lead) > len(kept.lead):
            kept.lead = a.lead
        kept.image = kept.image or a.image
    articles = sorted(by_key.values(), key=lambda a: a.published or "", reverse=True)

    langs: dict[str, int] = {}
    for a in articles:
        langs[a.lang] = langs.get(a.lang, 0) + 1
    report = {
        "edition": edition.isoformat(),
        "window_utc": [start.isoformat(), end.isoformat()],
        "store_total": len(store),
        "dropped_source_disabled": disabled,
        "dropped_wrong_lang": wrong_lang,
        "dropped_empty_title": empty,
        "dropped_no_date": no_date,
        "opinion_separated": opinion,
        "dropped_out_of_window": out_of_window,
        "merged_same_title": dup_title,
        "articles": len(articles),
        "by_lang": langs,
        "by_source": _count(articles, "source"),
    }
    return articles, report


def _opinion_kind(a: Article) -> str | None:
    # 저장해 둔 값 대신 매번 다시 판별한다 — 판별 규칙을 고치면 누적분에도 바로 반영되도록
    return detect_opinion(a.title, a.url, "opinion" if "opinion" in a.sections else "")


def _is_opinion(a: Article) -> bool:
    return _side_kind(a) is None and _opinion_kind(a) is not None


PICK = "column_pick"   # 지정 칼럼 피드의 section. "column_pick:<연재명>" 이면 연재 이름 (S23b)


def pick_series(sections: list[str]) -> list[str]:
    """지정 칼럼 피드 section 들에서 연재 이름 (S23b). 이름 없는 "column_pick" 은 빈 이름."""
    return sorted({s[len(PICK) + 1:] if s.startswith(PICK + ":") else "" for s in sections
                   if s == PICK or s.startswith(PICK + ":")})


def _side_kind(a: Article) -> str | None:
    """뉴스·논평 말고 따로 싣는 것: 'pick'(지정 칼럼, S22d) / 'analysis'(분석·해설, S22c) / 'interview'(인터뷰 후보, S27) / None.
    인터뷰 후보는 뉴스에서도 그대로 쓰인다 (뉴스 기사이기도 해서) — 분석·해설 면에 따로 한 번 더 싣는 것은 AI 가 고른 것만."""
    if pick_series(a.sections):
        return "pick"
    if _opinion_kind(a) is None and detect_analysis(a.title, a.url, "analysis" if "analysis" in a.sections else ""):
        return "analysis"
    if _opinion_kind(a) is None and detect_interview(a.title, a.lead):
        return "interview"
    return None


def _side_copy(a: Article, src) -> Article:
    a = copy.deepcopy(a)
    a.country, a.lean, a.media_type, a.weight, a.paywall = src.country, src.lean, src.type, src.weight, src.paywall
    a.lead = clean_lead(cap_lead(a.lead))
    if a.lead and title_key(a.lead).startswith(title_key(a.title)[:20]):
        a.lead = ""
    return a


ANALYSIS_EXTRA_HOURS = 24   # 분석 기사는 하루 늦게 읽어도 되므로 시간창 앞으로 하루 더


def prepare_side(store: dict[str, Article], edition: date, cfg: Config, sources: Sources, kind: str,
                 history_dir: Path | None = None) -> list[Article]:
    """분석·해설(kind='analysis'): 시간창 + 앞 하루, 같은 매체 같은 제목은 하나, 매체 가중치·최신순.
    지정 칼럼(kind='pick'): 누적분 전체(격주 연재라 하루 창엔 없을 때가 많음), 최신순."""
    start, end = edition_window(edition, cfg, history_dir)
    start -= timedelta(hours=ANALYSIS_EXTRA_HOURS)
    by_name = {s.name: s for s in sources.sources}
    seen: dict[tuple[str, str], Article] = {}
    for a in store.values():
        src = by_name.get(a.source)
        if src is None or not src.enabled or (src.langs and a.lang not in src.langs) or not a.published:
            continue
        if _side_kind(a) != kind:
            continue
        if kind == "pick" and len(pick_series(a.sections)) > 1:
            continue   # 같은 매체의 두 연재 검색에 걸린 글 — 어느 연재인지 모른다 (S23b: Economist 칼럼은 Google 뉴스 검색)
        t = datetime.fromisoformat(a.published)
        if t >= end or (kind in ("analysis", "interview") and t < start):
            continue
        key = (a.source, title_key(a.title))
        if key not in seen:
            seen[key] = _side_copy(a, src)
    return sorted(seen.values(), key=lambda a: (a.published or ""), reverse=True)


def prepare_opinions(
    store: dict[str, Article], edition: date, cfg: Config, sources: Sources, history_dir: Path | None = None
) -> list[Article]:
    """논평·사설: 뉴스와 같은 시간창. 같은 매체 같은 제목은 하나만."""
    start, end = edition_window(edition, cfg, history_dir)
    by_name = {s.name: s for s in sources.sources}
    seen: dict[tuple[str, str], Article] = {}
    for a in store.values():
        src = by_name.get(a.source)
        if src is None or not src.enabled or (src.langs and a.lang not in src.langs) or not a.published:
            continue
        if not _is_opinion(a):
            continue
        t = datetime.fromisoformat(a.published)
        if not (start <= t < end):
            continue
        a = copy.deepcopy(a)
        a.opinion = _opinion_kind(a)
        a.country, a.lean, a.media_type, a.weight, a.paywall = src.country, src.lean, src.type, src.weight, src.paywall
        a.lead = clean_lead(cap_lead(a.lead))
        if a.lead and title_key(a.lead).startswith(title_key(a.title)[:20]):
            a.lead = ""  # 제목을 되풀이한 리드 (Google 뉴스 요약 등)
        key = (a.source, title_key(a.title))
        if key not in seen:
            seen[key] = a
    return sorted(seen.values(), key=lambda a: (a.opinion != "editorial", a.country != "KR", -a.weight, a.published or ""))


def _count(articles: list[Article], attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for a in articles:
        k = getattr(a, attr)
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def to_jsonable(articles: list[Article]) -> list[dict]:
    return [asdict(a) for a in articles]
