"""손가락 밀기 넘김 (2026-10-21 "세로에서 넘기거나 돌아가는 터치가 잘 안 먹힌다").

오른쪽→왼쪽 밀기 = 다음 쪽, 왼쪽→오른쪽 = 이전 쪽 — 세로 한 쪽 화면(넘김 라이브러리)·한 면 보기·동작 줄이기 모두.
세로로 더 많이 움직인 손짓(스크롤)은 넘기지 않는다.
"""
import pytest

from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)

SWIPE = """([x0, x1, y0, y1]) => {
  const book = document.getElementById('book');
  const t = (x, y) => new Touch({identifier: 1, target: book, clientX: x, clientY: y});
  book.dispatchEvent(new TouchEvent('touchstart', {touches: [t(x0, y0)], changedTouches: [t(x0, y0)], bubbles: true}));
  book.dispatchEvent(new TouchEvent('touchmove', {touches: [t(x1, y1)], changedTouches: [t(x1, y1)], bubbles: true}));
  book.dispatchEvent(new TouchEvent('touchend', {touches: [], changedTouches: [t(x1, y1)], bubbles: true}));
}"""


def _cur(page):
    return page.evaluate("NEWS.state().current")


@pytest.mark.parametrize("w,h,view,reduced", [(390, 844, "flip", False), (375, 812, "flip", False), (820, 1180, "flip", False),
                                              (390, 844, "scroll", False), (390, 844, "flip", True)])
def test_swipe_left_next_right_prev(browser, tmp_path, w, h, view, reduced):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, w, h, reduced=reduced)
    if view == "scroll":
        page.evaluate("NEWS.setView('scroll')")
        page.wait_for_timeout(300)
    assert _cur(page) == 0
    page.evaluate(SWIPE, [w * 0.8, w * 0.2, 400, 410])      # 오른쪽 → 왼쪽
    page.wait_for_timeout(1200)
    assert _cur(page) == 1
    page.evaluate(SWIPE, [w * 0.8, w * 0.2, 400, 405])
    page.wait_for_timeout(1200)
    assert _cur(page) == 2
    page.evaluate(SWIPE, [w * 0.2, w * 0.8, 400, 400])      # 왼쪽 → 오른쪽
    page.wait_for_timeout(1200)
    assert _cur(page) == 1
    page.evaluate(SWIPE, [w * 0.5, w * 0.35, 200, 600])     # 세로 스크롤 손짓은 넘기지 않음
    page.wait_for_timeout(800)
    assert _cur(page) == 1
    ctx.close()
    assert not errors, errors
