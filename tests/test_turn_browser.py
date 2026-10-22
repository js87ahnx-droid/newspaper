"""넘김 엔진·모서리 제목·자세히 창 닫기 (S28a~c, 2026-10-23 사용자 요청).

1. 넘기는 애니메이션이 부자연스럽고 버벅임 → 직접 만든 넘김: 손가락을 따라가고, transform·opacity 만 바꾼다
4. 모서리 근처 기사 제목을 누르면 넘김 동작이 겹침 → 누르기는 누르기, 8px 넘게 가로로 끌어야 넘김
5. 자세히 창 바깥(지면 부분)을 눌러도 잘 안 닫힘 → 창에 직접 click, 바깥에서 누르고 뗀 것만
"""
import pytest

from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)

TOUCH = """async (pts) => {
  const book = document.getElementById('book');
  const t = (x, y) => new Touch({identifier: 1, target: book, clientX: x, clientY: y});
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const [x0, y0] = pts[0];
  book.dispatchEvent(new TouchEvent('touchstart', {touches: [t(x0, y0)], changedTouches: [t(x0, y0)], bubbles: true, cancelable: true}));
  for (const [x, y, wait] of pts.slice(1)) {
    await sleep(wait);
    book.dispatchEvent(new TouchEvent('touchmove', {touches: [t(x, y)], changedTouches: [t(x, y)], bubbles: true, cancelable: true}));
  }
  const [xe, ye] = pts[pts.length - 1];
  book.dispatchEvent(new TouchEvent('touchend', {touches: [], changedTouches: [t(xe, ye)], bubbles: true, cancelable: true}));
}"""


def _st(page):
    return page.evaluate("NEWS.state()")


def _no_survey(page):
    page.evaluate("document.getElementById('survey') && document.getElementById('survey').remove()")


def test_small_drag_returns_and_drag_follows_finger(browser, tmp_path):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, 1180, 820)
    _no_survey(page)
    box = page.locator("#book").bounding_box()
    x0, y0 = box["x"] + box["width"] - 40, box["y"] + box["height"] * 0.6
    page.mouse.move(x0, y0)
    page.mouse.down()
    for i in range(1, 6):                       # 쪽 폭의 1/4 쯤, 천천히
        page.mouse.move(x0 - i * 30, y0)
        page.wait_for_timeout(40)
    mid = page.evaluate("""() => { const p = document.querySelector('#book .page[data-page="1"]');
        return {turning: NEWS.state().turning, tf: p.style.transform}; }""")
    page.wait_for_timeout(200)                  # 멈췄다 놓기 = 튕김 아님
    page.mouse.up()
    page.wait_for_timeout(800)
    st = _st(page)
    ctx.close()
    assert not errors, errors
    assert mid["turning"] is True and "rotateY(-" in mid["tf"]    # 끄는 동안 오른쪽 쪽이 책등을 축으로 돈다
    assert st["current"] == 0 and st["turning"] is False          # 반을 안 넘기고 놓으면 제자리


def test_quick_flick_turns_even_if_short(browser, tmp_path):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, 390, 844)
    page.evaluate(TOUCH, [[300, 400], [270, 401, 40], [230, 402, 40]])   # 70px 를 80ms 에
    page.wait_for_timeout(800)
    cur = _st(page)["current"]
    ctx.close()
    assert not errors, errors
    assert cur == 1


@pytest.mark.parametrize("w,h", [(390, 844), (1180, 820)])
def test_back_turn_is_animated(browser, tmp_path, w, h):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, w, h)
    page.evaluate("NEWS.goTo(4)")
    page.evaluate("NEWS.go(-1)")
    during = _st(page)["turning"]
    page.wait_for_timeout(900)
    st = _st(page)
    ctx.close()
    assert not errors, errors
    assert during is True and st["turning"] is False
    assert st["current"] == (3 if w < h else 2)


@pytest.mark.parametrize("w,h", [(390, 844), (1180, 820)])
def test_turn_does_not_relayout_each_frame(browser, tmp_path, w, h):  # noqa: F811
    """넘기는 동안 레이아웃은 시작·끝 몇 번뿐 (예전 라이브러리는 한 번 넘김에 20~40번)."""
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, w, h)
    page.wait_for_timeout(300)
    cdp = ctx.new_cdp_session(page)
    cdp.send("Performance.enable")

    def layouts():
        return {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}["LayoutCount"]
    l0 = layouts()
    page.evaluate("NEWS.go(1)")
    page.wait_for_timeout(900)
    n = layouts() - l0
    st = _st(page)
    ctx.close()
    assert not errors, errors
    assert st["current"] == (1 if w < h else 2)
    assert n <= 5, f"넘김 한 번에 레이아웃 {n}번"


def _corner_title(page):
    """보이는 오른쪽 쪽에서 가장 아래(모서리 쪽) 기사 제목 링크의 오른쪽 끝 글자 위치."""
    return page.evaluate("""() => {
      const cur = NEWS.state().current, p = document.querySelector('#book .page[data-page="' + (cur + 1) + '"]');
      const links = [...p.querySelectorAll('a[data-detail]')].filter(a => a.getBoundingClientRect().height > 0);
      links.sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom);
      const r = links[0].getClientRects(), last = r[r.length - 1];
      return {x: last.right - 6, y: last.top + last.height / 2, bookRight: document.getElementById('book').getBoundingClientRect().right};
    }""")


@pytest.mark.parametrize("how", ["mouse", "tap"])
def test_corner_title_press_opens_reader_without_turning(browser, tmp_path, how):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, 1180, 820)
    _no_survey(page)
    pt = _corner_title(page)
    assert pt["x"] > pt["bookRight"] / 2 + 200          # 오른쪽 쪽 아래 제목 (모서리 쪽)
    if how == "mouse":
        page.mouse.click(pt["x"], pt["y"])
    else:
        page.touchscreen.tap(pt["x"], pt["y"])
    page.wait_for_timeout(800)
    r = page.evaluate("({open: !document.getElementById('reader').hidden, cur: NEWS.state().current, turning: NEWS.state().turning})")
    ctx.close()
    assert not errors, errors
    assert r == {"open": True, "cur": 0, "turning": False}


@pytest.mark.parametrize("w,h", [(1180, 820), (390, 844)])
def test_reader_closes_on_backdrop_only(browser, tmp_path, w, h):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, w, h)
    _no_survey(page)
    page.evaluate("NEWS.goTo(2)")
    before = _st(page)["current"]
    issue = page.evaluate("document.querySelector('#flow article.item[data-issue]').dataset.issue")
    is_open = "!document.getElementById('reader').hidden"
    page.evaluate(f"NEWS.openReader('{issue}')")
    panel = page.locator("#reader .reader-panel").bounding_box()
    # 창 안 누르기 → 그대로
    page.mouse.click(panel["x"] + panel["width"] / 2, panel["y"] + 60)
    inside = page.evaluate(is_open)
    # 창 안에서 누르고 바깥에서 떼기(글 끌기) → 그대로
    page.mouse.move(panel["x"] + 40, panel["y"] + 80)
    page.mouse.down()
    page.mouse.move(4, h - 4)
    page.mouse.up()
    dragged = page.evaluate(is_open)
    # 바깥 누르기 → 닫힘 (마우스, 손가락 탭 모두)
    page.mouse.click(4, h - 4)
    by_click = not page.evaluate(is_open)
    page.evaluate(f"NEWS.openReader('{issue}')")
    page.touchscreen.tap(4, h - 4)
    page.wait_for_timeout(200)
    by_tap = not page.evaluate(is_open)
    after = _st(page)["current"]
    ctx.close()
    assert not errors, errors
    assert inside and dragged and by_click and by_tap
    assert after == before


def test_drag_starting_on_title_turns_without_opening(browser, tmp_path):  # noqa: F811
    """제목 위에서 시작해도 가로로 끌면 넘김 — 놓은 자리의 링크는 눌리지 않는다 (휴대폰은 지면 대부분이 제목·링크)."""
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, 1180, 820)
    _no_survey(page)
    pt = _corner_title(page)
    page.mouse.move(pt["x"], pt["y"])
    page.mouse.down()
    for i in range(1, 16):
        page.mouse.move(pt["x"] - i * 45, pt["y"])
    page.mouse.up()
    page.wait_for_timeout(900)
    r = page.evaluate("({open: !document.getElementById('reader').hidden, cur: NEWS.state().current})")
    ctx.close()
    assert not errors, errors
    assert r == {"open": False, "cur": 2}
