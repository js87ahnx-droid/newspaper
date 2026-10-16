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
CFG = load_config()


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
        "media_type": "종합지", "weight": 1.0, "paywall": False, "kind": "rss", "title": "기사",
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
