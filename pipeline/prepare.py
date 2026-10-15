"""2단계 정제: 누적 저장소에서 그날 호의 시간창 기사만 고르고 중복을 없앤다."""
from __future__ import annotations

import copy
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .collect import Article
from .settings import Config, Sources
from .textutil import cap_lead, title_key


def edition_window(edition: date, cfg: Config) -> tuple[datetime, datetime]:
    """호 날짜 → [전날 start, 당일 end) 의 UTC 경계. 시작은 포함, 끝은 제외."""
    tz = ZoneInfo(cfg.timezone)
    sh, sm = map(int, cfg.window.start.split(":"))
    eh, em = map(int, cfg.window.end.split(":"))
    start = datetime.combine(edition - timedelta(days=1), time(sh, sm), tz)
    end = datetime.combine(edition, time(eh, em), tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def current_edition(now: datetime, cfg: Config) -> date:
    """지금 발행할 호: 가장 최근에 끝난 시간창의 날짜 (06:00 이후면 오늘, 이전이면 어제)."""
    tz = ZoneInfo(cfg.timezone)
    local = now.astimezone(tz)
    eh, em = map(int, cfg.window.end.split(":"))
    return local.date() if local.time() >= time(eh, em) else local.date() - timedelta(days=1)


def prepare(
    store: dict[str, Article], edition: date, cfg: Config, sources: Sources
) -> tuple[list[Article], dict]:
    """sources 는 수집 뒤 바뀌었을 수 있으므로(성향 라벨·가중치 수정, 매체 끄기) 여기서 다시 적용한다."""
    start, end = edition_window(edition, cfg)
    by_name = {s.name: s for s in sources.sources}
    no_date = out_of_window = dup_title = disabled = wrong_lang = 0
    in_window: list[Article] = []
    for a in store.values():
        src = by_name.get(a.source)
        if src is None or not src.enabled:
            disabled += 1
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
        "dropped_no_date": no_date,
        "dropped_out_of_window": out_of_window,
        "merged_same_title": dup_title,
        "articles": len(articles),
        "by_lang": langs,
        "by_source": _count(articles, "source"),
    }
    return articles, report


def _count(articles: list[Article], attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for a in articles:
        k = getattr(a, attr)
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def to_jsonable(articles: list[Article]) -> list[dict]:
    return [asdict(a) for a in articles]
