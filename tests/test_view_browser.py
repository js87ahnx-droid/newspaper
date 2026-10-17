"""S16 한 면 보기·스크롤·줌·전체화면 — 실제 브라우저로 측정.

기준 (project-plan.md S16):
- 한 면 보기에서 면 전체가 화면 폭에 맞고, 스크롤로 다음 면, 줌 1~3배 (터치 시뮬레이션)
- 보기 전환 후에도 읽던 면 유지
- 전체화면 버튼이 지원 브라우저에서 주소창을 숨기고, 미지원이면 홈 화면 추가 안내
"""
import pytest

from tests.test_render_browser import browser, make_site  # noqa: F401  (픽스처)

PINCH = """(f) => { const el = document.querySelector('#book .scroller'); const r = el.getBoundingClientRect();
  const t = (id, x, y) => new Touch({identifier: id, target: el, clientX: r.left + x, clientY: r.top + y});
  const fire = (type, a, b) => el.dispatchEvent(new TouchEvent(type, {touches: [a, b], targetTouches: [a, b],
      changedTouches: [a, b], bubbles: true, cancelable: true}));
  fire('touchstart', t(1, 150, 200), t(2, 250, 200));
  fire('touchmove', t(1, 150 - 50 * (f - 1), 200), t(2, 250 + 50 * (f - 1), 200));
  el.dispatchEvent(new TouchEvent('touchend', {touches: [], changedTouches: [], bubbles: true}));
  return NEWS.state().zoom; }"""


def open_(browser, index, w, h, view=None):  # noqa: F811
    ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=True, reduced_motion="reduce")
    init = "localStorage.setItem('news.survey', '2099-W01');"
    if view:
        init += f"localStorage.setItem('viewMode', '{view}');"
    ctx.add_init_script(f"try{{{init}}}catch(e){{}}")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(index.as_uri())
    page.wait_for_function("window.NEWS && window.NEWS.state().pages > 0")
    page.evaluate("document.getElementById('survey') && document.getElementById('survey').remove()")
    return ctx, page, errors


@pytest.mark.parametrize("w,h", [(1180, 820), (820, 1180), (390, 844)])
def test_scroll_view_fits_scrolls_and_zooms(browser, tmp_path, w, h):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, errors = open_(browser, index, w, h)
    flip_pages = page.evaluate("NEWS.state().pages")
    page.evaluate("NEWS.goTo(4)")
    before = page.evaluate("NEWS.state().current")
    page.click('[data-act="view"]')
    st = page.evaluate("NEWS.state()")
    geo = page.evaluate("""() => { const s = document.querySelector('#book .scroller');
        const r = document.querySelector('#book .page[data-page]').getBoundingClientRect();
        return {pw: r.width, ph: r.height, vw: s.clientWidth, vh: s.clientHeight,
                sw: document.scrollingElement.scrollWidth, iw: innerWidth}; }""")
    assert st["mode"] == "scroll" and st["pages"] == flip_pages
    assert st["current"] == before                       # 읽던 면 유지
    assert geo["pw"] <= geo["vw"] + 1 and geo["ph"] <= geo["vh"] + 1   # 한 면이 한 화면에
    assert geo["sw"] <= geo["iw"]
    # 스크롤로 다음 면
    page.evaluate("(() => { const s = document.querySelector('#book .scroller'); s.scrollTop += s.clientHeight; })()")
    page.wait_for_timeout(150)
    assert page.evaluate("NEWS.state().current") == before + 1
    # 두 손가락 줌: 1.5배, 상한 3배, 축소 하한 1배
    assert abs(page.evaluate(PINCH, 1.5) - 1.5) < 0.05
    assert page.evaluate(PINCH, 6) == 3
    for _ in range(6):   # 3배 → 0.5씩 → 1배에서 버튼이 꺼진다
        if page.evaluate("document.querySelector('[data-act=\"zoom-\"]').disabled"):
            break
        page.click('[data-act="zoom-"]')
    assert page.evaluate("NEWS.state().zoom") == 1
    assert page.evaluate("document.querySelector('[data-act=\"zoom-\"]').disabled")
    # 확대한 채로 가로로 끌 수 있다
    page.evaluate("NEWS.setZoom(3)")
    assert page.evaluate("(() => { const s = document.querySelector('#book .scroller'); return s.scrollWidth > s.clientWidth; })()")
    keep = page.evaluate("NEWS.state().current")
    page.click('[data-act="view"]')
    back = page.evaluate("NEWS.state()")
    ctx.close()
    assert back["mode"] == "flip" and back["current"] in (keep, keep - (keep % (2 if back["spread"] else 1)))
    assert not errors, errors


def test_view_mode_remembered(browser, tmp_path):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, _ = open_(browser, index, 1180, 820)
    page.click('[data-act="view"]')
    page.reload()
    page.wait_for_function("window.NEWS && window.NEWS.state().pages > 0")
    mode = page.evaluate("NEWS.state().mode")
    label = page.evaluate("document.querySelector('[data-act=\"view\"]').textContent")
    ctx.close()
    assert mode == "scroll" and label == "펼침"


def test_fullscreen_supported_and_fallback_tip(browser, tmp_path):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, _ = open_(browser, index, 1180, 820)
    page.click('[data-act="fullscreen"]')
    page.wait_for_timeout(300)
    on = page.evaluate("!!document.fullscreenElement")
    page.click('[data-act="fullscreen"]')
    page.wait_for_timeout(300)
    off = not page.evaluate("!!document.fullscreenElement")
    ctx.close()
    assert on and off
    # 미지원 브라우저(아이폰 Safari 등): 홈 화면 추가 안내
    ctx, page, _ = open_(browser, index, 390, 844)
    page.evaluate("""Object.defineProperty(document, 'fullscreenEnabled', {value: false, configurable: true});
                     Object.defineProperty(document, 'webkitFullscreenEnabled', {value: false, configurable: true});""")
    page.click('[data-act="fullscreen"]')
    tip = page.evaluate("(() => { const t = document.getElementById('fsTip'); return t && !t.hidden ? t.textContent : ''; })()")
    ctx.close()
    assert "홈 화면에 추가" in tip


@pytest.mark.parametrize("w,h", [(320, 640), (375, 812), (390, 844), (1024, 768)])
@pytest.mark.parametrize("view", ["flip", "scroll"])
def test_toolbar_fits(browser, tmp_path, w, h, view):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, _ = open_(browser, index, w, h, view=view)
    right = page.evaluate("Math.max(...[...document.querySelectorAll('#toolbar button')].filter(b => b.offsetParent).map(b => b.getBoundingClientRect().right))")
    acts = page.evaluate("[...document.querySelectorAll('#toolbar button')].filter(b => b.offsetParent).map(b => b.dataset.act)")
    ctx.close()
    assert right <= w
    assert {"view", "fullscreen", "settings"} <= set(acts)
