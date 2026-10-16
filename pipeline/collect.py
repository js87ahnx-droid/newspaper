"""1단계 수집: 켜진 피드를 모두 읽어 누적 저장소(store)에 합친다.

시간창(11시간)을 피드 하나가 다 담지 못하므로 시간창 안에서 여러 번 실행해 쌓는다.
같은 기사는 정규화한 URL로 한 번만 남는다. 기사 본문은 읽지도 저장하지도 않는다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import httpx

from .settings import Feed, Source, Sources
from .textutil import cap_lead, clean_text, detect_lang, detect_opinion, normalize_url, parse_date

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (personal news digest; RSS reader)"
RETRIES = 2
STORE_KEEP_DAYS = 4  # 시간창 최대 72시간 + 여유. 연속성은 data/history 로 따로 계산한다


@dataclass
class Article:
    id: str
    url: str                 # 표시·링크용 원래 주소
    source: str
    country: str
    lean: str
    media_type: str
    weight: float
    paywall: bool
    kind: str                # rss | google_news
    title: str
    lead: str
    lang: str
    published: str | None    # UTC ISO 8601, 모르면 None
    date_source: str         # feed | page_meta
    sections: list[str] = field(default_factory=list)
    main: bool = False       # 매체 메인 피드에 실렸는지
    first_seen: str = ""
    image: str | None = None  # RSS가 준 대표 이미지 주소 (원 주소로만 띄우고 복사하지 않는다)
    opinion: str | None = None  # "editorial"(사설) / "column"(칼럼·논평) / None(뉴스)

    @classmethod
    def from_dict(cls, d: dict) -> "Article":
        return cls(**d)


@dataclass
class FeedResult:
    source: str
    section: str
    url: str
    ok: bool
    items: int = 0
    error: str = ""


def article_id(norm_url: str) -> str:
    return hashlib.sha1(norm_url.encode()).hexdigest()[:16]


_GNEWS_SUFFIX = re.compile(r"\s+-\s+[^-]{1,40}$")
_IMG_SRC = re.compile(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', re.I)
_IMG_EXT = re.compile(r"\.(jpe?g|png|webp|gif)(\?|$)", re.I)


def entry_image(entry) -> str | None:
    """RSS 항목이 직접 주는 대표 이미지 주소. 가장 큰 것을 고른다. 없으면 None."""
    cands: list[tuple[int, str]] = []
    for m in entry.get("media_content", []) or []:
        url = m.get("url", "")
        medium, typ = m.get("medium", ""), m.get("type", "")
        if url and (medium == "image" or typ.startswith("image/") or (not medium and not typ and _IMG_EXT.search(url))):
            cands.append((int(m.get("width") or 0) or 1, url))
    for m in entry.get("media_thumbnail", []) or []:
        if m.get("url"):
            cands.append((int(m.get("width") or 0) or 1, m["url"]))
    for enc in entry.get("enclosures", []) or []:
        if enc.get("type", "").startswith("image/") and enc.get("href"):
            cands.append((1, enc["href"]))
    cands = [(w, u) for w, u in cands if u.startswith(("http://", "https://"))]
    if cands:
        return max(cands, key=lambda c: c[0])[1]
    m = _IMG_SRC.search(entry.get("summary", "") or "")
    return m.group(1) if m else None


def entry_to_article(entry, src: Source, feed: Feed, now: datetime) -> Article | None:
    link = entry.get("link")
    title = clean_text(entry.get("title"))
    if not link or not title:
        return None
    if feed.kind == "google_news":
        # Google 뉴스 제목은 "제목 - 매체명" 형식이고 요약은 제목을 되풀이한 링크뿐이다
        title = _GNEWS_SUFFIX.sub("", title)
    if feed.title_must and feed.title_must not in title:
        return None
        lead = ""
    else:
        lead = cap_lead(clean_text(entry.get("summary")))
        if lead == title:
            lead = ""
    raw_date = entry.get("published") or entry.get("updated")
    published = parse_date(raw_date, src.country)
    # 제목으로 판별한다 (리드에는 다른 언어 인용·고유명사가 섞이기 쉽다)
    lang = detect_lang(title)
    if lang == "und":
        lang = detect_lang(lead)
    if lang == "zh" and src.country == "JP":
        lang = "ja"  # 한자만으로 된 일본어 제목
    if src.langs and lang not in src.langs:
        return None
    norm = normalize_url(link)
    return Article(
        id=article_id(norm),
        url=link,
        source=src.name,
        country=src.country,
        lean=src.lean,
        media_type=src.type,
        weight=src.weight,
        paywall=src.paywall,
        kind=feed.kind,
        title=title,
        lead=lead,
        lang=lang,
        published=published.isoformat() if published else None,
        date_source=feed.date_source,
        sections=[feed.section],
        main=feed.main,
        first_seen=now.isoformat(),
        image=None if feed.kind == "google_news" else entry_image(entry),
        opinion=detect_opinion(title, link, feed.section),
    )


async def fetch(client: httpx.AsyncClient, url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            r = await client.get(url)
            r.raise_for_status()
            return r.content
        except (httpx.HTTPError, OSError) as e:
            last = e
            # 4xx 는 다시 해도 같으므로 재시도하지 않는다 (429 제외)
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500 and e.response.status_code != 429:
                break
            if attempt < RETRIES:
                await asyncio.sleep(1.5 * (attempt + 1))
    raise last  # type: ignore[misc]


async def collect_feed(client, sem, src: Source, feed: Feed, now: datetime) -> tuple[FeedResult, list[Article]]:
    async with sem:
        try:
            body = await fetch(client, feed.url)
        except Exception as e:  # 피드 하나의 실패가 전체를 멈추지 않게 격리
            msg = f"{type(e).__name__}: {e}"[:300]
            log.warning("피드 실패 %s/%s: %s", src.name, feed.section, msg)
            return FeedResult(src.name, feed.section, feed.url, False, error=msg), []
    parsed = feedparser.parse(body)
    if not parsed.entries:
        msg = "항목 0개" + (f" (파싱 오류: {parsed.bozo_exception})" if parsed.bozo else "")
        log.warning("피드 실패 %s/%s: %s", src.name, feed.section, msg)
        return FeedResult(src.name, feed.section, feed.url, False, error=msg[:300]), []
    arts = [a for e in parsed.entries if (a := entry_to_article(e, src, feed, now))]
    return FeedResult(src.name, feed.section, feed.url, True, items=len(arts)), arts


_META_TIME = re.compile(
    r'<meta[^>]+(?:property|name)="(?:article:published_time|og:article:published_time|pubdate)"[^>]+content="([^"]+)"',
    re.I,
)


async def resolve_page_date(client, sem, art: Article) -> None:
    """피드에 발행 시각이 없는 매체: 기사 페이지 <head> 의 메타 태그에서 시각만 읽는다."""
    async with sem:
        try:
            body = await fetch(client, art.url)
        except Exception as e:  # 다음 수집 때 다시 시도한다
            log.info("페이지 시각 확인 실패 %s: %s", art.url, e)
            return
    head = body.decode("utf-8", errors="replace").split("</head>", 1)[0]
    m = _META_TIME.search(head)
    if m and (dt := parse_date(m.group(1), art.country)):
        art.published = dt.isoformat()


def merge(store: dict[str, Article], new: list[Article]) -> int:
    """누적 저장소에 합친다. 이미 있는 기사는 섹션·메인 여부만 보탠다. 새로 들어온 수를 돌려준다."""
    added = 0
    for a in new:
        old = store.get(a.id)
        if old is None:
            store[a.id] = a
            added += 1
            continue
        for s in a.sections:
            if s not in old.sections:
                old.sections.append(s)
        old.main = old.main or a.main
        if not old.published and a.published:
            old.published = a.published
        if not old.lead and a.lead:
            old.lead = a.lead
        if not old.image and a.image:
            old.image = a.image
        old.opinion = old.opinion or a.opinion
    return added


def load_store(path: Path) -> dict[str, Article]:
    if not path.exists():
        return {}
    store = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            a = Article.from_dict(json.loads(line))
            store[a.id] = a
    return store


def save_store(path: Path, store: dict[str, Article], now: datetime) -> int:
    """오래된 기사를 덜어 내고 저장. 덜어 낸 수를 돌려준다."""
    cutoff = now - timedelta(days=STORE_KEEP_DAYS)
    keep = {k: a for k, a in store.items() if datetime.fromisoformat(a.first_seen) >= cutoff}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for a in keep.values():
            f.write(json.dumps(asdict(a), ensure_ascii=False) + "\n")
    tmp.replace(path)
    return len(store) - len(keep)


async def collect(
    sources: Sources,
    store_path: Path,
    now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    own_client = client is None
    client = client or httpx.AsyncClient(headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
    sem = asyncio.Semaphore(8)
    try:
        jobs = [collect_feed(client, sem, s, f, now) for s in sources.sources if s.enabled for f in s.feeds]
        results = await asyncio.gather(*jobs)
        store = load_store(store_path)
        before = len(store)
        added = 0
        for _, arts in results:
            added += merge(store, arts)
        # 시각이 없는 기사(page_meta 매체)만 페이지를 확인한다. 한 번 확인된 기사는 다시 열지 않는다
        pending = [a for a in store.values() if a.published is None and a.date_source == "page_meta"]
        page_sem = asyncio.Semaphore(4)
        await asyncio.gather(*(resolve_page_date(client, page_sem, a) for a in pending))
    finally:
        if own_client:
            await client.aclose()
    pruned = save_store(store_path, store, now)
    feed_results = [r for r, _ in results]
    return {
        "collected_at": now.isoformat(),
        "feeds_total": len(feed_results),
        "feeds_ok": sum(r.ok for r in feed_results),
        "feeds_failed": [asdict(r) for r in feed_results if not r.ok],
        "store_before": before,
        "added": added,
        "page_dates_resolved": sum(1 for a in pending if a.published),
        "page_dates_missing": sum(1 for a in pending if not a.published),
        "pruned": pruned,
        "store_after": len(store) - pruned,
    }
