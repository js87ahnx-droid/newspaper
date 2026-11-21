"""S55a 자세히 창 두 장 넘기기 (시안 A). 가짜 중계 서버(reader.test)."""
from __future__ import annotations

import pytest

from tests.test_reader import ARTICLE, _open
from tests.test_render_browser import browser  # noqa: F401  (픽스처)
from tests.test_s54_browser import _blocked_and_paywall, _close, _open_title

ST = """() => { const w = document.querySelector('#reader .sw'); if (!w) return null;
  const tr = w.querySelector('.sw-track'), tabs = [...w.querySelectorAll('.sw-tab')], panes = [...w.querySelectorAll('.sw-pane')];
  return { tabs: tabs.map(t => t.textContent), sel: tabs.map(t => t.getAttribute('aria-selected')), role: w.querySelector('.sw-tabs').getAttribute('role'),
           roles: tabs.map(t => t.getAttribute('role')), ctl: tabs.map(t => !!document.getElementById(t.getAttribute('aria-controls'))),
           hidden: panes.map(p => p.getAttribute('aria-hidden')), vis: panes.map(p => !p.hidden && p.offsetHeight > 0),
           ps: panes[1].querySelectorAll('.rv-p').length,
           tabbable2: [...panes[1].querySelectorAll('a, button')].filter(x => x.tabIndex >= 0).length,
           bigHead: !!w.querySelector('.ft-h'), sw: document.scrollingElement.scrollWidth - innerWidth }; }"""

# 손으로 밀기 (S57 시안 C): 자세히 창 두 장 위에서 터치 시작 → dx·dy 만큼 옮겨 손 떼기
SWIPE = """([dx, dy]) => { const t = document.querySelector('#reader .sw-track'), r = t.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + 40, T = (x, y) => new Touch({ identifier: 1, target: t, clientX: x, clientY: y });
  t.dispatchEvent(new TouchEvent('touchstart', { touches: [T(x, y)], changedTouches: [T(x, y)], bubbles: true }));
  t.dispatchEvent(new TouchEvent('touchend', { touches: [], changedTouches: [T(x + dx, y + dy)], bubbles: true })); }"""
SEL = "() => [...document.querySelectorAll('#reader .sw-tab')].map(t => t.getAttribute('aria-selected'))"


@pytest.mark.parametrize("w,h", [(390, 844), (1180, 820)])
def test_two_pages_tabs_and_swipe(browser, tmp_path, monkeypatch, w, h):
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE))
    page.set_viewport_size({"width": w, "height": h})
    page.wait_for_timeout(500)
    _open_title(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_selector("#reader .sw .ft .rv-p", state="attached")
    s = page.evaluate(ST)
    assert s["tabs"] == ["요약", "전문"] and s["sel"] == ["true", "false"] and s["role"] == "tablist" and s["roles"] == ["tab", "tab"]
    assert all(s["ctl"]) and s["hidden"] == ["false", "true"] and s["vis"] == [True, False] and not s["bigHead"]
    assert s["ps"] == len(ARTICLE["paragraphs"]) and s["tabbable2"] == 0 and s["sw"] <= 0, s
    page.evaluate("() => document.querySelectorAll('#reader .sw-tab')[1].click()")   # 탭 누르기
    page.wait_for_function("() => document.querySelectorAll('#reader .sw-tab')[1].getAttribute('aria-selected') === 'true'")
    s = page.evaluate(ST)
    assert s["sel"] == ["false", "true"] and s["hidden"] == ["true", "false"] and s["tabbable2"] > 0, s
    assert s["vis"] == [False, True], s                                          # 한 장만 보임 (S57 시안 C)
    page.evaluate(SWIPE, [-120, 0])                                              # 같은 쪽으로 더 밀기 — 그대로
    assert page.evaluate(SEL) == ["false", "true"]
    page.evaluate(SWIPE, [30, 0])                                                # 조금만 밀기 — 그대로
    page.evaluate(SWIPE, [80, 200])                                              # 세로로 더 많이 — 스크롤로 보고 그대로
    assert page.evaluate(SEL) == ["false", "true"]
    page.evaluate(SWIPE, [120, 10])                                              # 오른쪽으로 밀고 떼기 → 요약
    page.wait_for_function("() => document.querySelectorAll('#reader .sw-tab')[0].getAttribute('aria-selected') === 'true'")
    assert page.evaluate(ST)["vis"] == [True, False]
    page.evaluate("() => document.querySelectorAll('#reader .sw-tab')[0].focus()")
    page.keyboard.press("ArrowRight")                                          # 방향키로 탭
    page.wait_for_function("() => document.querySelectorAll('#reader .sw-tab')[1].getAttribute('aria-selected') === 'true'")
    assert page.evaluate("() => !document.getElementById('reader').hidden")   # 방향키가 지면 넘기기로 새지 않음
    assert len([x for x in seen if x["method"] == "GET"]) == 1 and not errors, errors
    ctx.close()


def test_blocked_second_page_alternatives_and_back_resets(browser, tmp_path, monkeypatch):
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE), mutate=_blocked_and_paywall)
    _open_title(page, '[data-href*="world/x.html"]')
    s = page.evaluate(ST)
    assert s and s["tabs"] == ["요약", "같은 사건 전문"], s
    assert s["tabbable2"] == 0, s                                              # 안 보이는 장의 단추는 Tab 에서 빠짐 (리뷰 B1)
    page.evaluate("() => document.querySelectorAll('#reader .sw-tab')[1].click()")
    page.wait_for_timeout(500)
    page.evaluate("() => document.querySelector('#reader .ft-alt button').click()")   # 대체 기사 → 원문 창
    page.wait_for_selector(".readview .rv-p")
    page.evaluate("() => document.querySelector('.readview .rv-back').click()")       # 돌아가기
    page.wait_for_selector("#reader .sw")
    s = page.evaluate(ST)
    assert s["sel"] == ["true", "false"] and s["vis"] == [True, False], s      # 첫 장·첫 탭으로 맞춤
    assert not errors, errors
    ctx.close()


def test_failure_shows_alternatives_in_second_page(browser, tmp_path, monkeypatch):
    def mutate(ed):
        _blocked_and_paywall(ed)
        a = [i for i in ed["sections"]["international"] if not i.get("reserve")][0]
        a["source"], a["url"] = "Der Spiegel", "https://www.spiegel.de/ausland/fail-x"   # 읽을 수 있는 매체로 — 받기는 실패
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (502, {"ok": False, "reason": "원문 http 403"}), mutate=mutate)
    _open_title(page, '[data-href*="spiegel.de/ausland/fail-x"]')
    page.wait_for_selector("#reader .ft .rv-fail", state="attached")
    r = page.evaluate("() => ({ tabs: [...document.querySelectorAll('#reader .sw-tab')].map(t => t.textContent), pay: !!document.querySelector('#reader .ft-pay'), link: !!document.querySelector('#reader .ft .rv-link-big') })")
    assert r == {"tabs": ["요약", "전문"], "pay": True, "link": True}, r
    assert not errors, errors
    ctx.close()


def test_no_tabs_without_relay(browser, tmp_path, monkeypatch):
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE), configured=False)
    _open_title(page, "")
    assert page.evaluate(ST) is None and not errors
    _close(page)
    ctx.close()


def test_clean_title_strips_site_suffix(browser, tmp_path, monkeypatch):
    art = dict(ARTICLE, title="재배열된 제목 - 조선일보", site="조선일보")
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, art))
    _open_title(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_selector("#reader .ft .rv-p", state="attached")
    assert page.evaluate("() => document.querySelector('#reader .ft-title').textContent") == "재배열된 제목"
    ctx.close()


@pytest.mark.parametrize("w,h", [(1180, 820), (1366, 1024), (390, 844)])
def test_opinion_pages_fill_and_keep_group_order(browser, tmp_path, w, h):
    """S55c: 논평면 1편 덩어리 — 마지막 쪽 빼고 아래 여백 < 20%, 묶음마다 순서 그대로, 빠진 글 0(넉넉한 쪽), 넘침 0."""
    from tests.test_render_browser import make_site, open_page
    from tests.test_s54 import _op_edition

    def mutate(ed):
        _op_edition(ed)
        for k in range(9):
            for kind in ("editorials", "columns"):
                row = dict(ed["opinion"][kind][k % len(ed["opinion"][kind])])
                row["id"], row["title"] = f"x{kind}{k}", row["title"] + f" {k}"
                ed["opinion"][kind].append(row)
    index = make_site(tmp_path, mutate=mutate)
    ctx, page, errors = open_page(browser, index, w, h)
    m = page.evaluate("""() => { const used = inn => { const r = inn.getBoundingClientRect(); let b = r.top; [...inn.children].forEach(c => { const q = c.getBoundingClientRect(); if (q.height > 0) b = Math.max(b, q.bottom); }); return (b - r.top) / r.height; };
      const ps = [...document.querySelectorAll('#book .page.sec-opinion')];
      const grp = id => id.replace(/-\d+$/, '');
      const flow = [...document.querySelectorAll('#flow section[data-section=opinion] > article')].map(a => a.getAttribute('data-issue'));
      const book = ps.flatMap(p => [...p.querySelectorAll('.page-inner > article')].map(a => a.getAttribute('data-issue')));
      const order = [...new Set(flow.map(grp))].every(g => { const f = flow.filter(x => grp(x) === g), b = book.filter(x => grp(x) === g); return JSON.stringify(f.slice(0, b.length)) === JSON.stringify(b); });
      const breaks = [...document.querySelectorAll('#book .page.sec-opinion .page-inner > article.op-cont')].filter(a => { const p = a.previousElementSibling; return p && !p.classList.contains('sec-title') && p.getAttribute('data-group') !== a.getAttribute('data-group'); });   // 쪽 첫머리는 쪽 머리 "(계속)"으로
      const heads = !breaks.length || breaks.some(a => a.querySelector('.op-conth'));   // 다른 묶음 뒤 이어지는 덩어리엔 "(계속)" — 넘칠 때만 빠짐
      return { used: ps.map(p => used(p.querySelector('.page-inner'))), order, heads, cont: document.querySelectorAll('#flow .oplist.op-cont').length }; }""")
    st = page.evaluate("() => NEWS.state()")
    assert not errors and not st["overflow"], (errors, st["overflow"])
    assert m["order"] and m["cont"] > 0 and m["heads"], m                     # 다른 묶음 뒤 이어지는 덩어리엔 "(계속)" (리뷰 M1)
    assert all(u >= 0.8 for u in m["used"][:-1]), m["used"]
    ctx.close()


def test_swipe_by_hand_aligns_vertical(browser, tmp_path, monkeypatch):
    art = dict(ARTICLE, paragraphs=["긴 문단입니다. " * 60] * 12)
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, art))
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(400)
    _open_title(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_selector("#reader .ft .rv-p", state="attached")
    page.evaluate("() => document.querySelectorAll('#reader .sw-tab')[1].click()")
    page.wait_for_timeout(600)
    page.evaluate("() => { document.querySelector('#reader .reader-panel').scrollTop = 4000; }")
    page.evaluate(SWIPE, [120, 0])                                              # 손으로 요약으로
    page.wait_for_function("() => document.querySelectorAll('#reader .sw-tab')[0].getAttribute('aria-selected') === 'true'")
    page.wait_for_timeout(200)
    r = page.evaluate("""() => { const p = document.querySelector('#reader .reader-panel'), w = document.querySelector('#reader .sw');
        const top = w.getBoundingClientRect().top - p.getBoundingClientRect().top + p.scrollTop; return { st: p.scrollTop, top }; }""")
    assert r["st"] <= r["top"] + 2, r
    assert not errors, errors
    ctx.close()


@pytest.mark.parametrize("w,h", [(390, 844), (1180, 820)])
def test_panel_size_kept_when_swiping_to_full(browser, tmp_path, monkeypatch, w, h):
    """요약 → 전문으로 넘겨도 자세히 창 크기는 요약 때 그대로 (긴 전문은 창 안에서 스크롤). 닫고 다시 열면 고정을 푼다."""
    art = dict(ARTICLE, paragraphs=["긴 문단입니다. " * 60] * 12)
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, art))
    page.set_viewport_size({"width": w, "height": h})
    page.wait_for_timeout(400)
    _open_title(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_selector("#reader .ft .rv-p", state="attached")
    page.wait_for_timeout(300)
    PH = "() => { const p = document.querySelector('#reader .reader-panel').getBoundingClientRect(); return [Math.round(p.width), Math.round(p.height)]; }"
    before = page.evaluate(PH)
    page.evaluate("() => document.querySelectorAll('#reader .sw-tab')[1].click()")   # 탭으로 전문
    page.wait_for_timeout(600)
    assert page.evaluate(PH) == before, (before, page.evaluate(PH))
    assert page.evaluate("() => { const p = document.querySelector('#reader .reader-panel'); return p.scrollHeight > p.clientHeight; }")   # 전문은 창 안에서 스크롤
    page.evaluate(SWIPE, [120, 0])                                              # 손으로 요약으로
    page.wait_for_function("() => document.querySelectorAll('#reader .sw-tab')[0].getAttribute('aria-selected') === 'true'")
    page.wait_for_timeout(200)
    assert page.evaluate(PH) == before
    page.evaluate(SWIPE, [-120, 0])                                             # 손으로 전문으로
    page.wait_for_function("() => document.querySelectorAll('#reader .sw-tab')[1].getAttribute('aria-selected') === 'true'")
    page.wait_for_timeout(200)
    assert page.evaluate(PH) == before
    _close(page)
    assert page.evaluate("() => document.querySelector('#reader .reader-panel').style.height") == ""   # 다시 열 때는 고정 풂
    assert not errors, errors
    ctx.close()


def test_trackpad_wheel_switches_once_per_swipe(browser, tmp_path, monkeypatch):
    """S57 리뷰 M3: 터치패드 가로 밀기는 한 번의 밀기(작은 이벤트 여러 개)를 모아 50px 넘으면 한 번만 바꾼다. 세로 휠은 안 바꾼다."""
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE))
    page.set_viewport_size({"width": 1180, "height": 820})
    page.wait_for_timeout(300)
    _open_title(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_selector("#reader .ft .rv-p", state="attached")
    WHEEL = """([dx, dy, n, mode]) => { const t = document.querySelector('#reader .sw-track'); let blocked = 0;
      for (let i = 0; i < n; i++) { const e = new WheelEvent('wheel', { deltaX: dx, deltaY: dy, deltaMode: mode, bubbles: true, cancelable: true }); t.dispatchEvent(e); blocked += e.defaultPrevented; }
      return blocked; }"""
    assert page.evaluate(WHEEL, [0, 40, 5, 0]) == 0 and page.evaluate(SEL) == ["true", "false"]   # 세로 휠 — 그대로, 막지 않음
    page.wait_for_timeout(300)                                                    # 다른 손동작
    assert page.evaluate(WHEEL, [8, 0, 10, 0]) == 10                             # 작은 가로 이벤트 10개(80px) — 브라우저 '뒤로'는 막고
    assert page.evaluate(SEL) == ["false", "true"]                               # 전문으로 한 번
    page.evaluate(WHEEL, [-8, 0, 20, 0])                                         # 같은 밀기 안에서는 한 번만 — 바로 되돌지 않음
    assert page.evaluate(SEL) == ["false", "true"]
    page.wait_for_timeout(300)
    page.evaluate(WHEEL, [-3, 0, 2, 1])                                          # 줄 단위 휠(Firefox Shift+휠) 3줄×2 = 96px → 요약
    assert page.evaluate(SEL) == ["true", "false"]
    assert not errors, errors
    ctx.close()
