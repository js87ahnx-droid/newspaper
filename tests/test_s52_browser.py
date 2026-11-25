"""S52c 지난 호 목록의 발행 진행 상황 (시안 A). 로컬 서버로 docs/status.json 을 준다."""
from __future__ import annotations

import functools
import http.server
import json
import threading
from datetime import date, datetime, timedelta, timezone

import pytest

from pipeline.render import render_archive_index
from tests.test_render_browser import browser  # noqa: F401  (픽스처)

DATES = [date(2026, 11, 17), date(2026, 11, 16), date(2026, 11, 15)]
SIZES = [(1180, 820), (390, 844)]


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture
def site(tmp_path):
    docs = tmp_path / "docs"
    (docs / "archive").mkdir(parents=True)
    (docs / "archive" / "index.html").write_text(render_archive_index(DATES), encoding="utf-8")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(docs)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield docs, f"http://127.0.0.1:{srv.server_address[1]}/archive/"
    srv.shutdown()


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _status(docs, **kw):
    now = datetime.now(timezone.utc)
    s = {"date": "2026-11-18", "state": "running", "step": 4, "steps": 7, "label": "AI 요약·분석", "message": "",
         "started": _iso(now - timedelta(minutes=20)), "updated": _iso(now - timedelta(minutes=1)), "run": ""}
    s.update(kw)
    (docs / "status.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    return s


def _open(browser, url, w=1180, h=820, tz="Asia/Seoul", eta=False):
    ctx = browser.new_context(viewport={"width": w, "height": h}, timezone_id=tz)
    page = ctx.new_page()
    if not eta:   # S61 완료 예정(status.js)은 지금 시각에 따라 "발행 대기" 줄을 더한다 → 여기서는 빼고 S52 동작만 (= status.js 없을 때 그대로)
        page.route("**/static/status.js*", lambda r: r.abort())
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "404" not in m.text and "Failed to load" not in m.text else None)
    page.goto(url)
    page.wait_for_function("window.NEWS_STATUS")
    page.wait_for_timeout(400)
    return ctx, page, errors


READ = """() => { const lis = [...document.querySelectorAll('.archive ul > li')];
  const st = lis.map(li => ({ date: li.getAttribute('data-date'), cls: li.className, link: !!li.querySelector('a[href]'),
    badge: (li.querySelector('.st-badge') || {}).textContent || null, sub: (li.querySelector('.st-sub') || {}).textContent || null,
    bar: li.querySelector('.st-bar > i') ? li.querySelector('.st-bar > i').style.width : null,
    msg: (li.querySelector('.st-msg') || {}).textContent || null }));
  return { rows: st, sw: document.scrollingElement.scrollWidth, iw: innerWidth }; }"""


@pytest.mark.parametrize("w,h", SIZES)
def test_running_row_on_top(browser, site, w, h):
    docs, url = site
    s = _status(docs)
    ctx, page, errors = _open(browser, url, w, h, tz="America/New_York")   # 다른 시간대 기기에서도 KST 로
    r = page.evaluate(READ)
    top = r["rows"][0]
    kst = (datetime.strptime(s["updated"], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=9)).strftime("%H:%M")
    assert len(r["rows"]) == 4 and top["date"] is None and not top["link"] and "st-run" in top["cls"], r
    assert top["badge"] == "발행 중" and top["sub"].startswith("4/7 AI 요약·분석 중 · " + kst), top
    assert top["bar"] == "57.1%" and top["msg"] is None
    assert r["sw"] <= r["iw"] and not errors, (r, errors)
    ctx.close()


@pytest.mark.parametrize("w,h", SIZES)
def test_error_row_text_only(browser, site, w, h):
    docs, url = site
    _status(docs, state="error", step=5, label="지면 만들기", message="<img src=x onerror=\"window.__x=1\"> KeyError: 'lead'")
    ctx, page, errors = _open(browser, url, w, h)
    r = page.evaluate(READ)
    top = r["rows"][0]
    assert top["badge"] == "발행 실패" and top["sub"].startswith("5/7 지면 만들기에서 멈춤 · ") and top["bar"] is None, top
    assert top["msg"] == "<img src=x onerror=\"window.__x=1\"> KeyError: 'lead'"                 # 글자 그대로
    assert page.evaluate("() => window.__x === undefined && !document.querySelector('.st-msg img')")
    assert r["sw"] <= r["iw"] and not errors, (r, errors)
    ctx.close()


@pytest.mark.parametrize("kw", [{"state": "done", "date": "2026-11-17"}, {"date": "2026-11-01"}, {"state": "error", "date": "2026-11-01"}, None])
def test_nothing_added(browser, site, kw):
    docs, url = site
    if kw is not None:
        _status(docs, **kw)
    ctx, page, errors = _open(browser, url)
    r = page.evaluate(READ)
    assert len(r["rows"]) == 3 and not any(x["badge"] or x["sub"] for x in r["rows"]) and not errors, (r, errors)
    ctx.close()


def test_done_not_yet_in_list_links(browser, site):
    docs, url = site
    _status(docs, state="done", step=7, label="올리기")
    ctx, page, errors = _open(browser, url)
    r = page.evaluate(READ)
    top = r["rows"][0]
    assert len(r["rows"]) == 4 and top["link"] and top["badge"] == "발행 완료" and top["sub"] == "목록 반영 중 — 눌러서 열기", top
    assert page.evaluate("() => document.querySelector('.archive ul > li a').getAttribute('href')") == "2026-11-18/"
    ctx.close()


def test_rerun_of_listed_date_attaches(browser, site):
    docs, url = site
    _status(docs, date="2026-11-16", step=5, label="지면 만들기")
    ctx, page, errors = _open(browser, url)
    r = page.evaluate(READ)
    mid = r["rows"][1]
    assert len(r["rows"]) == 3 and mid["date"] == "2026-11-16" and mid["link"] and mid["badge"] == "발행 중", r
    assert mid["sub"].startswith("5/7 지면 만들기 중") and mid["bar"] == "71.4%" and not errors
    ctx.close()


def test_stale_running(browser, site):
    docs, url = site
    now = datetime.now(timezone.utc)
    _status(docs, started=_iso(now - timedelta(minutes=126)), updated=_iso(now - timedelta(minutes=70)))
    ctx, page, errors = _open(browser, url)
    top = page.evaluate(READ)["rows"][0]
    assert top["badge"] == "멈춘 것 같음" and "마지막 갱신" in top["sub"] and top["bar"] is None, top
    ctx.close()


def test_running_to_done_reloads_and_no_store(browser, site):
    docs, url = site
    _status(docs)
    ctx, page, errors = _open(browser, url)
    reqs = []
    page.on("request", lambda q: reqs.append(q.url) if "status.json" in q.url else None)
    _status(docs, state="done", step=7, label="올리기")
    with page.expect_navigation():
        page.evaluate("() => NEWS_STATUS.load()")
    assert reqs and "?t=" in reqs[0]
    src = page.content()
    assert 'cache: "no-store"' in src
    ctx.close()
