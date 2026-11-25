"""S61 발행 전 화면: 오늘 호 덮개(시안 A)와 지난 호 목록 완료 예정(②). 로컬 서버로 status.json 을 주고 시각을 고정한다."""
from __future__ import annotations

import functools
import http.server
import json
import threading
from datetime import date, datetime, timedelta, timezone

import pytest

from pipeline.render import render_archive_index, render_html
from pipeline.settings import load_config, load_interests, load_sources
from tests.test_render_browser import browser, make_site  # noqa: F401  (픽스처)

KST = timezone(timedelta(hours=9))
P = "2026-11-25"           # 페이지(어제) 호
D = "2026-11-26"           # 오늘 나올 호
# 걸리는 시간 25·30·38분 → 중앙값 30분, 시작 06:34·06:34·05:34 → 중앙값 06:34 KST
RECENT = [{"date": "2026-11-22", "started": "2026-11-21T20:34:00Z", "finished": "2026-11-21T20:59:00Z"},
          {"date": "2026-11-24", "started": "2026-11-23T21:34:00Z", "finished": "2026-11-23T22:04:00Z"},
          {"date": "2026-11-25", "started": "2026-11-24T21:34:00Z", "finished": "2026-11-24T22:12:00Z"}]
LOCKED = ["front", "prev", "next", "zoom-", "zoom+", "view", "fullscreen", "font-", "font+", "settings"]


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def _serve(root):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("s61")
    held = []
    index = make_site(tmp, edition_date=P, n_issues=30, mutate=held.append)
    root = index.parent
    arch = root / "archive" / P
    arch.mkdir(parents=True)
    arch.joinpath("index.html").write_text(render_html(held[0], load_config(), load_interests(), load_sources(), base="../../"), encoding="utf-8")
    root.joinpath("archive", "index.html").write_text(
        render_archive_index([date(2026, 11, 25), date(2026, 11, 24), date(2026, 11, 23)]), encoding="utf-8")
    srv, url = _serve(root)
    yield root, url
    srv.shutdown()


def _kst(h, m, day=26):
    return datetime(2026, 11, day, h, m, tzinfo=KST)


def _z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _status(root, **kw):
    s = {"date": P, "state": "done", "step": 7, "steps": 7, "label": "올리기", "message": "",
         "started": "2026-11-24T21:34:00Z", "updated": "2026-11-24T22:12:00Z", "run": "", "recent": RECENT}
    s.update(kw)
    (root / "status.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    return s


def _running(root, step=3, label="편집", started=_kst(6, 34), updated=_kst(6, 51), **kw):
    return _status(root, **{"date": D, "state": "running", "step": step, "label": label, "started": _z(started), "updated": _z(updated), **kw})


def _open(browser, url, now, w=390, h=844, tz="Asia/Seoul"):
    ctx = browser.new_context(viewport={"width": w, "height": h}, timezone_id=tz, has_touch=True)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.clock.set_fixed_time(now)
    page.goto(url)
    page.wait_for_function("window.NEWS_PEND || window.NEWS_STATUS")
    page.wait_for_timeout(700)
    return ctx, page, errors


CARD = """() => { const p = document.querySelector('.pend'); if (!p) return null;
  const q = s => (p.querySelector(s) || {}).textContent || null, c = p.querySelector('.pend-card').getBoundingClientRect();
  return { phase: p.querySelector('.pend-card').getAttribute('data-phase'), big: q('.pend-big'), eta: q('.pend-eta'), step: q('.pend-step'),
    bar: p.querySelector('.pend-bar > i') ? p.querySelector('.pend-bar > i').style.width : null, btn: q('.pend-btn'),
    mast: q('.pend-title'), tb: document.querySelector('#toolbar .tb-title').textContent,
    inView: c.left >= 0 && c.top >= 0 && c.right <= innerWidth && c.bottom <= innerHeight,
    sw: document.scrollingElement.scrollWidth, iw: innerWidth }; }"""


# ---------- 1면 덮개 ----------
@pytest.mark.parametrize("w,h,tz", [(390, 844, "Asia/Seoul"), (1180, 820, "America/New_York")])
def test_wait_cover_before_start(browser, site, w, h, tz):
    root, url = site
    _status(root)                                                   # 어제 호 완료 — 오늘은 아직 시작 전
    ctx, page, errors = _open(browser, url, _kst(6, 10), w, h, tz)
    c = page.evaluate(CARD)
    assert c and c["phase"] == "wait" and c["big"] == "11월 26일자 발행 대기", c
    assert c["eta"] == "07:05 KST 완료 예정" and c["step"] == "곧 시작" and c["bar"] == "0%", c   # 06:34 + 30분 → 5분 올림
    assert c["mast"] == "11월 26일자 뉴스" and c["tb"] == "11월 26일자 뉴스" and c["btn"] == "11월 25일자 호 보기", c
    assert c["inView"] and c["sw"] <= c["iw"] and not errors, (c, errors)
    ctx.close()


@pytest.mark.parametrize("w,h", [(390, 844), (1180, 820)])
def test_running_cover_and_locks(browser, site, w, h):
    root, url = site
    _running(root)
    ctx, page, errors = _open(browser, url, _kst(6, 52), w, h)
    c = page.evaluate(CARD)
    assert c["phase"] == "run" and c["big"] == "11월 26일자 발행 중" and c["eta"] == "07:05 KST 완료 예정", c
    assert c["step"] == "3/7 편집 중 · 06:51 갱신 (06:34 시작)" and c["bar"] == "42.9%" and c["inView"], c
    dis = page.evaluate("(ls) => ls.map(a => { const b = document.querySelector('#toolbar [data-act=\"' + a + '\"]'); return !b || b.disabled; })", LOCKED)
    assert all(dis), dis
    assert page.evaluate("() => !document.querySelector('#toolbar [data-act=\"theme\"]').disabled && !!document.querySelector('#toolbar a.tb-link[href*=\"archive\"]')")
    cur = page.evaluate("() => NEWS.state().current")
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(300)
    hit = page.evaluate("() => { const r = document.getElementById('book').getBoundingClientRect(); const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height * 0.8); return !!(e && e.closest('.pend')); }")
    assert page.evaluate("() => NEWS.state().current") == cur and hit and not errors
    ctx.close()


@pytest.mark.parametrize("now,kw,phase,eta", [
    (_kst(7, 20), {}, "late", "예정보다 늦어지는 중"),
    (_kst(8, 50), {"started": _kst(6, 34), "updated": _kst(7, 30)}, "stuck", "멈춘 것 같음 · 마지막 갱신 07:30"),
    (_kst(7, 15), {"state": "error", "step": 5, "label": "지면 만들기", "updated": _kst(7, 14), "message": "<b>x</b>"}, "error",
     "5/7 지면 만들기에서 멈춤 · 07:14"),
    (_kst(7, 40), None, "delayed", "발행이 늦어지고 있음"),                # 시작 예상 06:34 + 60분이 지나도 시작 안 함
])
def test_late_stuck_error_delayed(browser, site, now, kw, phase, eta):
    root, url = site
    if kw is None:
        _status(root)
    else:
        _running(root, **kw)
    ctx, page, errors = _open(browser, url, now)
    c = page.evaluate(CARD)
    assert c["phase"] == phase and c["eta"] == eta, c
    if phase != "late":
        assert c["bar"] is None and c["step"] is None, c
    assert page.evaluate("() => !document.querySelector('.pend b')") and not errors
    ctx.close()


@pytest.mark.parametrize("case", ["before6", "same_date", "no_status", "archive_page", "broken_json"])
def test_not_covered(browser, site, case):
    root, url = site
    (root / "status.json").unlink(missing_ok=True)
    now = _kst(6, 30)
    if case == "before6":
        _status(root); now = _kst(5, 50)
    elif case == "same_date":
        _status(root); now = _kst(6, 30, day=25)                  # 페이지가 이미 오늘 호
    elif case == "archive_page":
        _status(root); url = url + f"archive/{P}/"
    elif case == "broken_json":
        (root / "status.json").write_text("{oops", encoding="utf-8")
    ctx, page, errors = _open(browser, url, now)
    assert page.evaluate(CARD) is None and not errors, errors
    assert page.evaluate("() => !document.querySelector('#toolbar [data-act=\"next\"]').disabled")
    ctx.close()


def test_running_before_six_covers(browser, site):
    root, url = site
    _running(root, step=2, label="수집", started=_kst(5, 34), updated=_kst(5, 40))
    ctx, page, errors = _open(browser, url, _kst(5, 45))
    c = page.evaluate(CARD)
    assert c["phase"] == "run" and c["eta"] == "06:05 KST 완료 예정", c
    ctx.close()


def test_dismiss_stays_for_tab_and_toast_on_done(browser, site):
    root, url = site
    _running(root)
    ctx, page, errors = _open(browser, url, _kst(6, 52))
    page.click(".pend-btn")
    assert page.evaluate(CARD) is None
    assert page.evaluate("() => !document.querySelector('#toolbar [data-act=\"next\"]').disabled")
    assert page.evaluate("() => document.querySelector('#toolbar .tb-title').textContent") == "11월 25일자 뉴스"
    page.reload()
    page.wait_for_function("window.NEWS_PEND")
    page.wait_for_timeout(700)
    assert page.evaluate(CARD) is None                                  # 이 탭에선 다시 덮지 않음
    done = _status(root, date=D, state="done", started=_z(_kst(6, 34)), updated=_z(_kst(7, 3)))
    page.evaluate("(s) => NEWS_PEND.draw(s)", done)                    # 걷은 탭: 새로 고치지 않고 알림
    page.wait_for_timeout(300)
    assert page.evaluate("() => document.querySelector('.pend-toast').textContent") == "11월 26일자가 나왔습니다 · 열기"
    assert page.evaluate(CARD) is None and not errors
    ctx.close()


def test_done_reloads_once_then_button(browser, site):
    root, url = site
    _running(root)
    ctx, page, errors = _open(browser, url, _kst(6, 52))
    assert page.evaluate(CARD)["phase"] == "run"
    done = _status(root, date=D, state="done", started=_z(_kst(6, 34)), updated=_z(_kst(7, 3)))
    with page.expect_navigation():
        page.evaluate("(s) => NEWS_PEND.draw(s)", done)
    page.wait_for_function("window.NEWS_PEND")
    page.wait_for_timeout(700)
    c = page.evaluate(CARD)                                            # 새로 고쳐도 옛 호 (Pages 반영 지연)
    assert c["phase"] == "done" and c["big"] == "11월 26일자 발행 완료" and c["eta"] == "새 지면 반영 중" and c["btn"] == "새로 고침", c
    navs = []
    page.on("framenavigated", lambda f: navs.append(f.url))
    page.evaluate("(s) => NEWS_PEND.draw(s)", done)
    page.wait_for_timeout(500)
    assert not navs and not errors                                     # 더 자동으로 새로 고치지 않음
    ctx.close()


def test_eta_functions(browser, site):
    root, url = site
    _status(root)
    ctx, page, errors = _open(browser, url, _kst(6, 10), tz="America/New_York")
    r = page.evaluate("""() => { const E = NEWS_ETA;
      return { m0: E.median([]), m1: E.median([5]), m2: E.median([10, 20]), m3: E.median([30, 10, 20]),
               d0: E.duration({}), s0: E.startGuess({}), d1: E.duration({recent: [{started: '2026-11-25T21:00:00Z', finished: '2026-11-25T21:40:00Z'}]}),
               date: E.parts(Date.now()).date, hm: E.hm(Date.now()) }; }""")
    assert r == {"m0": None, "m1": 5, "m2": 15, "m3": 20, "d0": 35, "s0": 395, "d1": 40, "date": D, "hm": "06:10"}, r
    ctx.close()


def test_no_recent_uses_defaults(browser, site):
    root, url = site
    _status(root, recent=None)
    ctx, page, errors = _open(browser, url, _kst(6, 10))
    assert page.evaluate(CARD)["eta"] == "07:10 KST 완료 예정"           # 06:35 + 35분
    ctx.close()


# ---------- 목록 ② ----------
ROWS = """() => [...document.querySelectorAll('.archive ul > li')].map(li => ({ date: li.getAttribute('data-date'),
  link: !!li.querySelector('a[href]'), badge: (li.querySelector('.st-badge') || {}).textContent || null,
  sub: (li.querySelector('.st-sub') || {}).textContent || null }))"""


@pytest.mark.parametrize("now,kw,badge,sub", [
    (_kst(6, 10), None, "발행 대기", "곧 시작 · 07:05 KST 완료 예정"),
    (_kst(7, 40), None, "발행 대기", "발행이 늦어지고 있음"),
    (_kst(6, 52), {}, "발행 중", "3/7 편집 중 · 06:51 갱신 (06:34 시작) · 07:05 KST 완료 예정"),
    (_kst(7, 20), {}, "발행 중", "3/7 편집 중 · 06:51 갱신 (06:34 시작) · 예정보다 늦어지는 중"),
])
def test_archive_rows(browser, site, now, kw, badge, sub):
    root, url = site
    if kw is None:
        _status(root)
    else:
        _running(root, **kw)
    ctx, page, errors = _open(browser, url + "archive/", now, tz="America/New_York")
    rows = page.evaluate(ROWS)
    assert len(rows) == 4 and rows[0]["date"] is None and not rows[0]["link"], rows
    assert rows[0]["badge"] == badge and rows[0]["sub"] == sub and not errors, (rows, errors)
    ctx.close()


@pytest.mark.parametrize("case", ["before6", "listed", "no_status"])
def test_archive_no_wait_row(browser, site, case):
    root, url = site
    (root / "status.json").unlink(missing_ok=True)
    now = _kst(6, 30)
    if case == "before6":
        _status(root); now = _kst(5, 50)
    elif case == "listed":
        _status(root); now = _kst(6, 30, day=25)                   # 목록 맨 위가 이미 오늘
    ctx, page, errors = _open(browser, url + "archive/", now)
    rows = page.evaluate(ROWS)
    assert len(rows) == 3 and not any(r["badge"] for r in rows) and not errors, (rows, errors)
    ctx.close()
