"""S58 같은 사건 전문에서 밀기(창 전체) · 위부터 차례로 번역. 가짜 중계 서버(reader.test)."""
from __future__ import annotations

import json

from tests.test_reader import ARTICLE, _open
from tests.test_render_browser import browser  # noqa: F401  (픽스처)
from tests.test_s54_browser import _blocked_and_paywall, _close, _open_title

# 창 안 아무 요소(sel) 위, 위에서 frac 높이 자리에서 터치 시작 → dx 만큼 옮겨 손 떼기
SWIPE_AT = """([sel, frac, dx]) => { const t = document.querySelector(sel), r = t.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height * frac, T = (x, y) => new Touch({ identifier: 1, target: t, clientX: x, clientY: y });
  t.dispatchEvent(new TouchEvent('touchstart', { touches: [T(x, y)], changedTouches: [T(x, y)], bubbles: true }));
  t.dispatchEvent(new TouchEvent('touchend', { touches: [], changedTouches: [T(x + dx, y + 4)], bubbles: true })); }"""
SEL = "() => [...document.querySelectorAll('#reader .sw-tab')].map(t => t.getAttribute('aria-selected'))"


def test_swipe_back_from_short_alternatives_page(browser, tmp_path, monkeypatch):
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE), mutate=_blocked_and_paywall)
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(300)
    _open_title(page, '[data-href*="world/x.html"]')                          # 막힌 매체 → 둘째 장 "같은 사건 전문"
    page.wait_for_selector("#reader .sw")
    assert page.evaluate("() => [...document.querySelectorAll('#reader .sw-tab')].map(t => t.textContent)") == ["요약", "같은 사건 전문"]
    page.evaluate("() => document.querySelectorAll('#reader .sw-tab')[1].click()")
    page.wait_for_timeout(200)
    r = page.evaluate("""() => { const p = document.querySelector('#reader .reader-panel').getBoundingClientRect(), w = document.querySelector('#reader .sw').getBoundingClientRect();
        return { empty: p.bottom - w.bottom }; }""")
    assert r["empty"] > 150, r                                                   # 장 아래 빈 창이 넉넉 (창 크기는 요약 때 그대로)
    # 빈 창(.reader-panel 자신, 아래쪽 90% 높이)에서 오른쪽으로 밀기 → 요약
    assert page.evaluate("() => getComputedStyle(document.querySelector('#reader .reader-panel')).touchAction") == "pan-y pinch-zoom"
    page.evaluate(SWIPE_AT, ["#reader .reader-panel", 0.9, -120])                 # 둘째 장에서 왼쪽으로 — 그대로 (리뷰 N4)
    assert page.evaluate(SEL) == ["false", "true"]
    page.evaluate(SWIPE_AT, ["#reader .reader-panel", 0.9, 120])
    assert page.evaluate(SEL) == ["true", "false"]
    page.evaluate(SWIPE_AT, ["#reader .reader-panel", 0.9, 30])                  # 조금만 — 그대로
    assert page.evaluate(SEL) == ["true", "false"]
    page.evaluate(SWIPE_AT, ["#reader .sw-tabs", 0.5, -120])                     # 위 막대(탭 줄)에서 왼쪽으로 → 같은 사건 전문
    assert page.evaluate(SEL) == ["false", "true"]
    page.evaluate(SWIPE_AT, ["#reader .reader-bar", 0.5, 120])                   # 닫기 막대에서 오른쪽으로 → 요약
    assert page.evaluate(SEL) == ["true", "false"]
    assert not errors, errors
    ctx.close()


def test_swipe_in_reader_without_pages_does_nothing(browser, tmp_path, monkeypatch):
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE), configured=False)
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(300)
    _open_title(page, "")
    assert page.evaluate("() => !document.querySelector('#reader .sw')")
    assert page.evaluate("() => getComputedStyle(document.querySelector('#reader .reader-panel')).touchAction") == "auto"   # 두 장 없으면 그대로 (리뷰 N5)
    page.evaluate(SWIPE_AT, ["#reader .reader-panel", 0.5, 120])
    page.evaluate(SWIPE_AT, ["#reader .reader-panel", 0.5, -120])
    assert page.evaluate("() => !document.getElementById('reader').hidden") and not errors, errors
    _close(page)
    page.evaluate(SWIPE_AT, ["#book", 0.5, -10])                                 # 닫힌 뒤에도 오류 없음
    assert not errors, errors
    ctx.close()


# ---------- S58b 위부터 차례로 번역 ----------
TWELVE = dict(ARTICLE, paragraphs=[f"Paragraph {n} of a placeholder article. " + "Filler words that stand in for a real sentence. " * 8 for n in range(1, 13)])   # 430자 남짓 — 묶음 7개 (1 + 2×5 + 1)
HOLD = """() => { window.__tr = []; const of = window.fetch;
  window.fetch = (u, o) => String(u).endsWith('/translate') ? new Promise(res => window.__tr.push({ texts: JSON.parse(o.body).texts, res, done: false })) : of(u, o); }"""
# n 번째 붙잡은 요청에 답하기: bad 에 든 자리는 빈 글로(서버가 실패한 묶음을 빈 글로 채우는 것처럼)
ANSWER = """([n, bad]) => { const r = window.__tr[n]; r.done = true;
  r.res(new Response(JSON.stringify({ ok: true, texts: r.texts.map((t, i) => bad.includes(i) ? '' : 'KO ' + t.split(' ')[1]) }), { headers: { 'Content-Type': 'application/json' } })); }"""
PENDING = "() => window.__tr.filter(r => !r.done).length"
PS = "() => [...document.querySelectorAll('#reader .ft .rv-p')].map(p => p.textContent.slice(0, 6))"

FAIL = """(n) => { const r = window.__tr[n]; r.done = true; r.res(new Response(JSON.stringify({ ok: false, reason: '키 없음' }), { headers: { 'Content-Type': 'application/json' } })); }"""
OPEN_ORIG = """() => document.querySelector('#flow article.item > .meta .orig-btn[data-href*="spiegel.de/ausland/x"]').click()"""


def _open_spiegel(browser, tmp_path, monkeypatch):
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, TWELVE), mutate=_blocked_and_paywall)
    iid = _open_title(page, '[data-href*="spiegel.de/ausland/x"]')
    page.wait_for_selector("#reader .ft .rv-lang .rv-tab", state="attached")
    page.evaluate(HOLD)
    return ctx, page, errors, iid


def test_translation_shows_top_first_without_waiting(browser, tmp_path, monkeypatch):
    ctx, page, errors, iid = _open_spiegel(browser, tmp_path, monkeypatch)
    page.evaluate("() => document.querySelector('#reader .ft .rv-lang .rv-tab').click()")
    page.wait_for_function("() => window.__tr.length === 6")
    page.wait_for_timeout(200)
    tr = page.evaluate("() => window.__tr.map(r => r.texts.length)")
    assert len(tr) == 6 and tr[0] <= 2, tr                                       # 동시에 6개, 첫 묶음은 작게
    assert page.evaluate("() => window.__tr[0].texts[0]").startswith("Paragraph 1 ")   # 위 묶음부터
    page.evaluate(ANSWER, [0, []])                                               # 첫 묶음만 답함 — 나머지는 아직
    page.wait_for_function("() => document.querySelector('#reader .ft .rv-p').textContent === 'KO 1'")
    ps = page.evaluate(PS)
    assert ps[1] == ("KO 2" if tr[0] == 2 else "Paragr") and ps[-1] == "Paragr", ps
    btn = page.evaluate("() => document.querySelector('#reader .ft .rv-lang .rv-tab').textContent")
    assert f"{tr[0]}/12 문단" in btn, btn
    page.wait_for_function("() => window.__tr.length === 7")                    # 하나 끝나면 다음 하나 (동시에 6개 이하)
    assert page.evaluate(PENDING) == 6
    # 둘째 묶음: 첫 문단만 빈 글로 → 그 문단만 한 번 더
    page.evaluate(ANSWER, [1, [0]])
    page.wait_for_function("() => window.__tr.length === 8")                    # 새로 나간 것 = 실패 문단만 다시
    retry_n = 7
    retry_text = page.evaluate("(n) => window.__tr[n].texts[0]", retry_n)
    assert retry_text == page.evaluate("() => window.__tr[1].texts[0]")
    # 나머지는 다 답하고, 다시 묻는 것은 또 빈 글 → 그 문단은 원문으로 남음
    for _ in range(30):
        n = page.evaluate("() => window.__tr.findIndex(r => !r.done)")
        if n < 0:
            break
        page.evaluate(ANSWER, [n, [0] if n == retry_n else []])
        page.wait_for_timeout(50)
    page.wait_for_selector("#reader .ft .rv-lang .rv-lang-note", state="attached")
    note = page.evaluate("() => document.querySelector('#reader .ft .rv-lang .rv-lang-note').textContent")
    assert "1개 문단은 옮기지 못했습니다" in note, note
    ps = page.evaluate(PS)
    assert sum(p == "Paragr" for p in ps) == 1 and sum(p.startswith("KO") for p in ps) == 11, ps
    # "다시" → 못 옮긴 문단 하나만 요청
    before = page.evaluate("() => window.__tr.length")
    page.evaluate("() => [...document.querySelectorAll('#reader .ft .rv-lang .rv-tab')].find(b => b.textContent === '다시').click()")
    page.wait_for_function("(n) => window.__tr.length === n + 1", arg=before)
    assert page.evaluate("(n) => window.__tr[n].texts", before) == [retry_text]
    page.evaluate(ANSWER, [before, []])
    page.wait_for_function("() => document.querySelector('#reader .ft .rv-lang .rv-lang-note').textContent === 'AI 번역'")
    assert all(p.startswith("KO") for p in page.evaluate(PS))
    # 한국어/원문 전환
    page.evaluate("() => [...document.querySelectorAll('#reader .ft .rv-lang .rv-tab')].find(b => b.textContent === '원문').click()")
    assert page.evaluate(PS)[0] == "Paragr"
    # 다시 열면 요청 없이 바로
    _close(page)
    page.evaluate("(i) => NEWS.openReader(i)", iid)
    page.wait_for_selector("#reader .ft .rv-lang .rv-tab", state="attached")
    n0 = page.evaluate("() => window.__tr.length")
    page.evaluate("() => document.querySelector('#reader .ft .rv-lang .rv-tab').click()")
    page.wait_for_timeout(200)
    assert page.evaluate("() => window.__tr.length") == n0 and all(p.startswith("KO") for p in page.evaluate(PS))
    assert not errors, errors
    ctx.close()


def test_translation_stops_on_close_and_resumes_missing_only(browser, tmp_path, monkeypatch):
    ctx, page, errors, iid = _open_spiegel(browser, tmp_path, monkeypatch)
    page.evaluate("() => document.querySelector('#reader .ft .rv-lang .rv-tab').click()")
    page.wait_for_function("() => window.__tr.length === 6")
    first3 = page.evaluate("() => window.__tr.flatMap(r => r.texts)")
    _close(page)                                                                  # 닫음 — 보낸 6개는 끝까지 받고, 새 묶음은 안 보냄
    for n in range(6):
        page.evaluate(ANSWER, [n, []])
    page.wait_for_timeout(500)
    assert page.evaluate("() => window.__tr.length") == 6
    page.evaluate("(i) => NEWS.openReader(i)", iid)                             # 다시 열고 번역 → 못 받은 문단만
    page.wait_for_selector("#reader .ft .rv-lang .rv-tab", state="attached")
    page.evaluate("() => document.querySelector('#reader .ft .rv-lang .rv-tab').click()")
    page.wait_for_function("() => window.__tr.length > 6")
    ps = page.evaluate(PS)
    assert sum(p.startswith("KO") for p in ps) == len(first3), ps               # 받은 것은 바로 한국어
    later = page.evaluate("() => window.__tr.slice(6).flatMap(r => r.texts)")
    assert not set(later) & set(first3)
    assert not errors, errors
    ctx.close()


def test_horizontal_wheel_not_blocked_without_pages(browser, tmp_path, monkeypatch):
    """S58 리뷰 M8: 두 장이 없는 창에서는 가로 휠을 막지 않는다."""
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE), configured=False)
    _open_title(page, "")
    blocked = page.evaluate("""() => { const p = document.querySelector('#reader .reader-panel');
      const e = new WheelEvent('wheel', { deltaX: 60, deltaY: 0, bubbles: true, cancelable: true }); p.dispatchEvent(e); return e.defaultPrevented; }""")
    assert blocked is False and not errors, errors
    ctx.close()


def test_reopen_while_in_flight_waits_instead_of_resending(browser, tmp_path, monkeypatch):
    """S58 리뷰 M1: 닫고 바로 다시 열어 번역하면, 보내 둔 문단은 다시 보내지 않고 그 결과를 받아 새 창에 넣는다."""
    ctx, page, errors, iid = _open_spiegel(browser, tmp_path, monkeypatch)
    page.evaluate("() => document.querySelector('#reader .ft .rv-lang .rv-tab').click()")
    page.wait_for_function("() => window.__tr.length === 6")
    _close(page)
    page.evaluate("(i) => NEWS.openReader(i)", iid)
    page.wait_for_selector("#reader .ft .rv-lang .rv-tab", state="attached")
    page.evaluate("() => document.querySelector('#reader .ft .rv-lang .rv-tab').click()")
    page.wait_for_function("() => window.__tr.length === 7")                    # 남은 묶음 하나만 새로
    page.wait_for_timeout(300)
    assert page.evaluate("() => window.__tr.length") == 7
    for n in range(7):
        page.evaluate(ANSWER, [n, [0] if n == 2 else []])                        # 보내 둔 것 중 한 문단은 실패 → 새 창이 한 번 더
        page.wait_for_timeout(30)
    page.wait_for_function("() => window.__tr.length === 8")
    assert page.evaluate("() => window.__tr[7].texts") == page.evaluate("() => [window.__tr[2].texts[0]]")
    page.evaluate(ANSWER, [7, []])
    page.wait_for_function("() => { const n = document.querySelector('#reader .ft .rv-lang .rv-lang-note'); return n && n.textContent === 'AI 번역'; }")
    assert all(p.startswith("KO") for p in page.evaluate(PS)), page.evaluate(PS)
    assert not errors, errors
    ctx.close()


def test_fatal_translate_error_stops_at_once(browser, tmp_path, monkeypatch):
    """S58 리뷰 M4: 키 없음 같은 실패는 남은 묶음을 보내지 않고 한 번 더도 안 하며 이유를 보인다."""
    ctx, page, errors, iid = _open_spiegel(browser, tmp_path, monkeypatch)
    page.evaluate("() => document.querySelector('#reader .ft .rv-lang .rv-tab').click()")
    page.wait_for_function("() => window.__tr.length === 6")
    for n in range(6):
        page.evaluate(FAIL, n)
    page.wait_for_function("() => document.querySelector('#reader .ft .rv-lang .rv-tab').textContent.includes('키 없음')")
    page.wait_for_timeout(300)
    assert page.evaluate("() => window.__tr.length") == 6                        # 일곱째 묶음·다시 묻기 없음
    assert not errors, errors
    ctx.close()


def test_reader_window_translates_top_first_and_stops_on_close(browser, tmp_path, monkeypatch):
    """S58 리뷰 M2: 원문 창 자동 번역도 위부터 — 첫 묶음만 와도 "n/13 문단", 닫으면 새 묶음 없음, 다시 열면 못 받은 것만."""
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, TWELVE), mutate=_blocked_and_paywall)
    page.evaluate(HOLD)
    page.evaluate(OPEN_ORIG)
    page.wait_for_function("() => window.__tr.length === 6")
    assert page.evaluate("() => window.__tr[0].texts.length") <= 2
    page.evaluate(ANSWER, [0, []])                                               # 자리가 나서 일곱째(마지막) 묶음이 나감
    page.wait_for_function("() => window.__tr.length === 7")
    page.wait_for_function("() => document.querySelector('.readview .rv-lang-note').textContent.includes('문단')")
    page.wait_for_timeout(100)
    note = page.evaluate("() => document.querySelector('.readview .rv-lang-note').textContent")
    k = page.evaluate("() => window.__tr[0].texts.length")
    assert f"{k}/13 문단" in note, note
    _close(page)
    for n in range(1, 7):
        page.evaluate(ANSWER, [n, [0] if n == 3 else []])                        # 닫은 뒤 한 문단 실패 — 닫힌 창은 다시 묻지 않음
    page.wait_for_timeout(500)
    assert page.evaluate("() => window.__tr.length") == 7                        # 닫은 뒤 새 요청 없음
    missing = page.evaluate("() => window.__tr[3].texts[0]")
    page.evaluate(OPEN_ORIG)
    page.wait_for_function("() => window.__tr.length > 7")
    later = page.evaluate("() => window.__tr.slice(7).flatMap(r => r.texts)")
    assert later == [missing], later                                             # 다시 열면 못 받은 것만
    assert not errors, errors
    ctx.close()
