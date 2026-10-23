"""수집·정제: 가짜 HTTP 응답으로 피드 실패 격리, 누적, 시간창 경계, 중복 제거를 검증한다."""
import asyncio
import json
import shutil
from datetime import timedelta, date, datetime, timezone

import httpx
import pytest

from pipeline.__main__ import main
from pipeline.collect import collect, load_store
from pipeline.prepare import current_edition, edition_window, prepare, target_edition
from pipeline.settings import ROOT, Sources, load_config

UTC = timezone.utc
_cfg = load_config()
# 시간창 경계 테스트는 06:00 마감을 기준으로 짠 것 — 설정의 마감(지금 05:30)과 무관하게 고정
CFG = _cfg.model_copy(update={"window": _cfg.window.model_copy(update={"end": "06:00"})})


def rss(items: list[tuple[str, str, str | None]]) -> bytes:
    """(제목, 링크, pubDate) 목록으로 RSS 문서를 만든다. pubDate 가 None 이면 생략."""
    body = "".join(
        f"<item><title>{t}</title><link>{l}</link><description>{t} 리드 문장입니다. 충분히 긴 요약.</description>"
        + (f"<pubDate>{d}</pubDate>" if d else "")
        + "</item>"
        for t, l, d in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>'.encode()


def make_sources(feeds: dict[str, list[dict]]) -> Sources:
    return Sources.model_validate(
        {
            "sources": [
                {"name": name, "country": "KR", "lean": "중도", "type": "종합지", "weight": 1.0,
                 "paywall": False, "enabled": True, "feeds": fl}
                for name, fl in feeds.items()
            ]
        }
    )


def client_for(routes: dict[str, httpx.Response | Exception]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        r = routes.get(str(request.url))
        if isinstance(r, Exception):
            raise r
        return r or httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(sources, store_path, routes, now):
    async def go():
        async with client_for(routes) as c:
            return await collect(sources, store_path, now=now, client=c)

    return asyncio.run(go())


NOW = datetime(2026, 10, 15, 20, 30, tzinfo=UTC)  # 10/16 05:30 KST


def test_one_feed_failing_does_not_stop_others(tmp_path):
    sources = make_sources(
        {
            "A": [{"section": "top", "url": "https://a.test/rss"}],
            "B": [{"section": "top", "url": "https://broken.test/rss"}],
            "C": [{"section": "top", "url": "https://c.test/rss"}],
        }
    )
    routes = {
        "https://a.test/rss": httpx.Response(200, content=rss([("가 기사", "https://a.test/1", "Thu, 15 Oct 2026 21:00:00 +0900")])),
        "https://broken.test/rss": httpx.ConnectError("DNS 실패"),
        "https://c.test/rss": httpx.Response(200, content=b"<html>not a feed</html>"),
    }
    report = run(sources, tmp_path / "store.jsonl", routes, NOW)
    assert report["feeds_ok"] == 1
    failed = {f["source"]: f["error"] for f in report["feeds_failed"]}
    assert set(failed) == {"B", "C"}
    assert "ConnectError" in failed["B"]
    assert "항목 0개" in failed["C"]
    assert len(load_store(tmp_path / "store.jsonl")) == 1


def test_accumulates_without_duplicates(tmp_path):
    sources = make_sources(
        {"A": [{"section": "top", "url": "https://a.test/rss", "main": True},
               {"section": "politics", "url": "https://a.test/pol"}]}
    )
    first = {
        "https://a.test/rss": httpx.Response(200, content=rss([("첫 기사", "https://a.test/1?utm_source=rss", "Thu, 15 Oct 2026 20:00:00 +0900")])),
        "https://a.test/pol": httpx.Response(200, content=rss([("첫 기사", "https://www.a.test/1", "Thu, 15 Oct 2026 20:00:00 +0900")])),
    }
    second = {
        "https://a.test/rss": httpx.Response(200, content=rss([
            ("둘째 기사", "https://a.test/2", "Fri, 16 Oct 2026 01:00:00 +0900"),
            ("첫 기사", "https://a.test/1", "Thu, 15 Oct 2026 20:00:00 +0900"),
        ])),
        "https://a.test/pol": httpx.Response(200, content=rss([])),
    }
    store_path = tmp_path / "store.jsonl"
    r1 = run(sources, store_path, first, NOW)
    r2 = run(sources, store_path, second, NOW)
    store = load_store(store_path)
    assert r1["added"] == 1 and r2["added"] == 1
    assert len(store) == 2
    first_art = next(a for a in store.values() if a.title == "첫 기사")
    assert sorted(first_art.sections) == ["politics", "top"]
    assert first_art.main is True


def test_page_meta_date_resolution_and_drop(tmp_path):
    sources = make_sources(
        {"H": [{"section": "top", "url": "https://h.test/rss", "date_source": "page_meta"}]}
    )
    routes = {
        "https://h.test/rss": httpx.Response(200, content=rss([
            ("시각 있는 페이지", "https://h.test/1", None),
            ("시각 없는 페이지", "https://h.test/2", None),
        ])),
        "https://h.test/1": httpx.Response(200, text='<html><head><meta name="article:published_time" '
                                                     'content="2026-10-15T22:00:00+09:00"/></head><body>본문</body></html>'),
        "https://h.test/2": httpx.Response(200, text="<html><head></head><body>본문</body></html>"),
    }
    report = run(sources, tmp_path / "store.jsonl", routes, NOW)
    assert report["page_dates_resolved"] == 1 and report["page_dates_missing"] == 1
    store = load_store(tmp_path / "store.jsonl")
    # 본문은 저장하지 않는다
    assert all("본문" not in a.lead for a in store.values())
    arts, prep = prepare(store, date(2026, 10, 16), CFG, sources)
    assert [a.title for a in arts] == ["시각 있는 페이지"]
    assert prep["dropped_no_date"] == 1


@pytest.mark.parametrize(
    "pub, inside",
    [
        # 직전 호 기록이 없으면 24시간: 전날 06:00 ~ 당일 06:00 KST
        ("Thu, 15 Oct 2026 05:59:59 +0900", False),
        ("Thu, 15 Oct 2026 06:00:00 +0900", True),
        ("Thu, 15 Oct 2026 19:00:00 +0900", True),
        ("Fri, 16 Oct 2026 05:59:59 +0900", True),
        ("Fri, 16 Oct 2026 06:00:00 +0900", False),
        # 같은 순간을 다른 표기로
        ("Wed, 14 Oct 2026 20:59:59 GMT", False),   # 10/15 05:59:59 KST
        ("2026-10-14T21:00:00Z", True),              # 10/15 06:00:00 KST
        ("2026-10-15T20:59:59+00:00", True),         # 05:59:59 KST
        ("Thu, 15 Oct 2026 17:00:00 -0400", False),  # 06:00:00 KST
        ("2026-10-16 05:59:59", True),               # 시간대 없음 → KR 매체이므로 KST
        ("2026-10-16 06:00:00", False),
    ],
)
def test_window_boundaries(tmp_path, pub, inside):
    sources = make_sources({"A": [{"section": "top", "url": "https://a.test/rss"}]})
    routes = {"https://a.test/rss": httpx.Response(200, content=rss([("경계 기사", "https://a.test/x", pub)]))}
    run(sources, tmp_path / "store.jsonl", routes, NOW)
    arts, _ = prepare(load_store(tmp_path / "store.jsonl"), date(2026, 10, 16), CFG, sources)
    assert (len(arts) == 1) is inside


def test_same_source_same_title_merged(tmp_path):
    sources = make_sources({"A": [{"section": "top", "url": "https://a.test/rss"}]})
    routes = {"https://a.test/rss": httpx.Response(200, content=rss([
        ("[단독] 같은 기사", "https://a.test/news/1", "Thu, 15 Oct 2026 22:00:00 +0900"),
        ("같은 기사", "https://a.test/amp/1", "Thu, 15 Oct 2026 22:05:00 +0900"),
    ]))}
    run(sources, tmp_path / "store.jsonl", routes, NOW)
    arts, rep = prepare(load_store(tmp_path / "store.jsonl"), date(2026, 10, 16), CFG, sources)
    assert len(arts) == 1 and rep["merged_same_title"] == 1


def test_window_and_edition():
    start, end = edition_window(date(2026, 10, 16), CFG)
    assert start == datetime(2026, 10, 14, 21, 0, tzinfo=UTC)   # 직전 호 없음 → 24시간
    assert end == datetime(2026, 10, 15, 21, 0, tzinfo=UTC)
    # 06:10 KST 발행 실행 → 그날 호, 05:50 수집 시각 → 전날 호가 가장 최근에 끝난 창
    assert current_edition(datetime(2026, 10, 15, 21, 10, tzinfo=UTC), CFG) == date(2026, 10, 16)
    assert current_edition(datetime(2026, 10, 15, 20, 50, tzinfo=UTC), CFG) == date(2026, 10, 15)
    # 수집이 채워 가는 호: 06:00 전이면 오늘 호, 뒤면 내일 호 (낮에도 다음 호를 채운다)
    assert target_edition(datetime(2026, 10, 15, 20, 50, tzinfo=UTC), CFG) == date(2026, 10, 16)
    assert target_edition(datetime(2026, 10, 15, 21, 0, tzinfo=UTC), CFG) == date(2026, 10, 17)
    assert target_edition(datetime(2026, 10, 16, 4, 30, tzinfo=UTC), CFG) == date(2026, 10, 17)   # 13:30 KST


def _publish(hist, d):
    hist.mkdir(parents=True, exist_ok=True)
    (hist / f"{d.isoformat()}.json").write_text('{"edition": "%s", "issues": []}' % d.isoformat(), encoding="utf-8")


def test_windows_contiguous_three_days(tmp_path):
    """연속 3일 발행: 각 호의 시작 = 직전 호의 끝 (빈틈·겹침 없음)."""
    hist = tmp_path / "history"
    windows = []
    for d in [date(2026, 10, 16), date(2026, 10, 17), date(2026, 10, 18)]:
        windows.append(edition_window(d, CFG, hist))
        _publish(hist, d)
    for (s1, e1), (s2, e2) in zip(windows, windows[1:]):
        assert s2 == e1
    assert all(e - s == timedelta(hours=24) for s, e in windows)


def test_window_after_missed_day_and_cap(tmp_path):
    hist = tmp_path / "history"
    _publish(hist, date(2026, 10, 16))
    # 10/17 발행을 빠뜨림 → 10/18 호는 10/16 06:00 부터 48시간
    s, e = edition_window(date(2026, 10, 18), CFG, hist)
    assert e - s == timedelta(hours=48) and s == datetime(2026, 10, 15, 21, 0, tzinfo=UTC)
    # max_hours(72) 보다 오래 비면 직전 호를 찾지 않고 24시간으로
    s, e = edition_window(date(2026, 10, 21), CFG, hist)
    assert e - s == timedelta(hours=24)


def test_source_settings_reapplied_at_prepare(tmp_path):
    """수집 뒤 sources.yaml 을 고쳐도(언어 제한, 라벨 변경, 매체 끄기) 다음 발행에 반영된다."""
    sources = make_sources({
        "A": [{"section": "top", "url": "https://a.test/rss"}],
        "B": [{"section": "top", "url": "https://b.test/rss"}],
    })
    routes = {
        "https://a.test/rss": httpx.Response(200, content=rss([
            ("한국어 기사", "https://a.test/1", "Thu, 15 Oct 2026 22:00:00 +0900"),
            ("日本語の記事です", "https://a.test/jp/1", "Thu, 15 Oct 2026 22:00:00 +0900"),
        ])),
        "https://b.test/rss": httpx.Response(200, content=rss([("B 기사", "https://b.test/1", "Thu, 15 Oct 2026 22:00:00 +0900")])),
    }
    run(sources, tmp_path / "store.jsonl", routes, NOW)
    store = load_store(tmp_path / "store.jsonl")
    assert len(store) == 3

    edited = sources.model_copy(deep=True)
    edited.sources[0].langs = ["ko"]
    edited.sources[0].lean = "진보"
    edited.sources[1].enabled = False
    arts, rep = prepare(store, date(2026, 10, 16), CFG, edited)
    assert [a.title for a in arts] == ["한국어 기사"]
    assert arts[0].lean == "진보"
    assert rep["dropped_wrong_lang"] == 1 and rep["dropped_source_disabled"] == 1


def test_langs_filter_at_collect(tmp_path):
    sources = make_sources({"A": [{"section": "top", "url": "https://a.test/rss"}]})
    sources.sources[0].langs = ["ko"]
    routes = {"https://a.test/rss": httpx.Response(200, content=rss([
        ("한국어 기사", "https://a.test/1", "Thu, 15 Oct 2026 22:00:00 +0900"),
        ("日本語の記事です", "https://a.test/jp/1", "Thu, 15 Oct 2026 22:00:00 +0900"),
    ]))}
    run(sources, tmp_path / "store.jsonl", routes, NOW)
    assert [a.lang for a in load_store(tmp_path / "store.jsonl").values()] == ["ko"]


def test_prepare_cli_writes_report(tmp_path):
    for name in ("config.yaml", "interests.yaml"):
        shutil.copy(ROOT / name, tmp_path / name)
    (tmp_path / "sources.yaml").write_text(
        "sources:\n  - {name: A, country: KR, lean: 중도, type: 종합지, weight: 1.0, paywall: false, enabled: true,"
        " feeds: [{section: top, url: 'https://a.test/rss'}]}\n",
        encoding="utf-8",
    )
    raw = tmp_path / "raw"
    raw.mkdir()
    art = {
        "id": "x1", "url": "https://a.test/1", "source": "A", "country": "KR", "lean": "중도",
        "media_type": "종합지", "weight": 1.0, "paywall": False, "kind": "rss", "title": "시험 기사 제목",
        "lead": "", "lang": "ko", "published": "2026-10-15T12:00:00+00:00", "date_source": "feed",
        "sections": ["top"], "main": False, "first_seen": "2026-10-15T12:30:00+00:00",
    }
    (raw / "store.jsonl").write_text(json.dumps(art, ensure_ascii=False) + "\n", encoding="utf-8")
    log = {"collected_at": "2026-10-15T20:50:00+00:00", "feeds_ok": 1, "feeds_total": 2, "added": 1,
           "feeds_failed": [{"source": "B", "section": "top", "url": "u", "ok": False, "items": 0, "error": "HTTP 403"}]}
    (raw / "collect-log.jsonl").write_text(json.dumps(log) + "\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "--data", str(tmp_path), "prepare", "--date", "2026-10-16"]) == 0
    report = json.loads((tmp_path / "run-report.json").read_text(encoding="utf-8"))
    assert report["articles"] == 1
    assert report["collect_runs"][0]["feeds_failed"][0]["error"] == "HTTP 403"


def test_url_must_filters_videos_and_ft_query_is_dropped():
    """S19e: Bloomberg 피드의 영상·뉴스레터는 거르고(url_must), FT 피드 주소의 ?syn-… 는 같은 기사로 합친다."""
    from pipeline.collect import entry_to_article
    from pipeline.settings import Feed, Source
    from pipeline.textutil import normalize_url
    feed = Feed(section="economy", url="https://feeds.bloomberg.com/markets/news.rss", url_must="/(news|opinion)/articles/")
    src = Source(name="Bloomberg", country="US", lean="경제지", type="경제지", weight=1.0, paywall=True, enabled=True, feeds=[feed])
    now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    mk = lambda u: {"link": u, "title": "Stocks rally", "summary": "x", "published": "Fri, 17 Oct 2026 10:00:00 GMT"}
    assert entry_to_article(mk("https://www.bloomberg.com/news/articles/2026-10-17/stocks"), src, feed, now)
    assert entry_to_article(mk("https://www.bloomberg.com/news/videos/2026-10-17/stocks"), src, feed, now) is None
    assert entry_to_article(mk("https://www.bloomberg.com/news/newsletters/2026-10-17/x"), src, feed, now) is None
    with pytest.raises(ValueError):
        Feed(section="x", url="https://a.b/", url_must="(")
    assert normalize_url("https://www.ft.com/content/abc?syn-25a6b1a6=1") == normalize_url("https://www.ft.com/content/abc")


def test_google_news_items_have_no_fake_lead():
    """Google 뉴스 요약은 '제목 + 매체명' 링크뿐 — 리드로 쓰지 않는다 (S9b 에서 빠졌던 줄, S20d 에서 발견). 공식 RSS 는 리드 유지."""
    from pipeline.collect import entry_to_article
    from pipeline.settings import Feed, Source
    now = datetime(2026, 10, 18, 1, tzinfo=timezone.utc)
    gn = Feed(section="top", url="https://news.google.com/rss/search?q=site:news.cn", kind="google_news")
    rss = Feed(section="top", url="https://a.test/rss")
    src = Source(name="신화통신", country="CN", lean="관영", type="통신", weight=0.6, paywall=False, enabled=True, feeds=[gn, rss])
    e = {"link": "https://news.google.com/rss/articles/X", "title": "高市早苗向靖国神社献祭品 - 新华网",
         "summary": "<a href='x'>高市早苗向靖国神社献祭品</a>&nbsp;新华网", "published": "Sat, 17 Oct 2026 23:00:00 GMT"}
    a = entry_to_article(e, src, gn, now)
    assert a.title == "高市早苗向靖国神社献祭品" and a.lead == "" and a.lang == "zh"
    b = entry_to_article({**e, "summary": "这是一段真正的导语，介绍了事件的背景和经过。"}, src, rss, now)
    assert b.lead.startswith("这是")


def test_late_market_reports_join_this_edition(tmp_path):
    """S28e: 시간창 끝 뒤 발행 시각까지(최대 3시간) 나온 시황 기사는 이번 호에 — 다른 기사는 다음 호로."""
    from email.utils import format_datetime
    _, end = edition_window(date(2026, 10, 16), CFG)
    at = lambda m: format_datetime(end + timedelta(minutes=m))   # noqa: E731
    sources = make_sources({"A": [{"section": "top", "url": "https://a.test/rss"}]})
    routes = {"https://a.test/rss": httpx.Response(200, content=rss([
        ("뉴욕증시, AI 우려에 나스닥 2% 급락 마감", "https://a.test/1", at(40)),
        ("정부, 내년 예산안 발표", "https://a.test/2", at(40)),
        ("뉴욕증시, 혼조 마감(종합)", "https://a.test/3", at(240)),        # 3시간 넘음
        ("코스피, 하락 출발", "https://a.test/4", at(-60)),                  # 시간창 안
    ]))}
    run(sources, tmp_path / "store.jsonl", routes, end + timedelta(hours=5))
    store = load_store(tmp_path / "store.jsonl")
    arts, rep = prepare(store, date(2026, 10, 16), CFG, sources, late_until=end + timedelta(hours=5))
    assert sorted(a.url for a in arts) == ["https://a.test/1", "https://a.test/4"] and rep["late_market"] == 1
    arts, _ = prepare(store, date(2026, 10, 16), CFG, sources, late_until=end + timedelta(minutes=30))   # 아직 안 나온 시각
    assert [a.url for a in arts] == ["https://a.test/4"]
    arts, _ = prepare(store, date(2026, 10, 16), CFG, sources)
    assert [a.url for a in arts] == ["https://a.test/4"]


def test_requested_picks_configured():
    """2026-10-23 사용자 요청: 중앙일보 "김학균의 이코노믹스"·NYT "The Interview" 를 지정 칼럼으로."""
    import re
    from pipeline.settings import load_sources
    feeds = {f.section: f for s in load_sources(ROOT).sources if s.enabled for f in s.feeds}
    kh, nyt = feeds["column_pick:김학균의 이코노믹스"], feeds["column_pick:The Interview (NYT)"]
    assert kh.title_must == "[김학균의 이코노믹스]"
    ok = "https://www.nytimes.com/2026/10/10/magazine/mirjana-spoljaric-interview.html"
    no = ["https://www.nytimes.com/2026/10/22/magazine/billionaire-millionaire-interviews.html",
          "https://www.nytimes.com/2026/10/21/magazine/patient-death-lying-ethics.html"]
    assert re.search(nyt.url_must, ok) and not any(re.search(nyt.url_must, u) for u in no)
