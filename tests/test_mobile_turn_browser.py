"""휴대폰에서도 넘김 애니메이션 (S32, 15차 요청 "모바일에서도 넘기는 애니메이션").

S32a: 기기의 동작 줄이기 설정이어도 펼침 보기는 종이 넘김.
S32b: 한 면 보기에서 밀어 넘기면 옛 화면 덮개가 돌며 넘어가고(다음) 앞 쪽이 되넘어온다(이전). 확대 중엔 덮개 없이.
"""
import pytest

from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)
from tests.test_swipe_browser import SWIPE

SHEETS = "document.querySelectorAll('#book .sheet').length"


@pytest.mark.parametrize("w,h", [(390, 844), (1180, 820)])
def test_reduced_motion_still_turns(browser, tmp_path, w, h):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, w, h, reduced=True)
    assert page.evaluate("NEWS.state().flip")
    page.click('[data-act="next"]')
    page.wait_for_timeout(120)
    mid = page.evaluate("NEWS.state().turning")   # 넘기는 중 (애니메이션)
    page.wait_for_timeout(1200)
    st = page.evaluate("NEWS.state()")
    if w < 700:   # 손가락으로 끌어도 넘김 애니메이션
        page.evaluate(SWIPE, [w * 0.8, w * 0.2, 400, 410])
        page.wait_for_timeout(1200)
        st2 = page.evaluate("NEWS.state().current")
    ctx.close()
    assert mid and not st["turning"]
    assert st["current"] == (2 if st["spread"] else 1)
    if w < 700:
        assert st2 == 2
    assert not errors, errors


@pytest.mark.parametrize("reduced", [False, True])
def test_scroll_view_turn_sheet(browser, tmp_path, reduced):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, 390, 844, reduced=reduced)
    page.evaluate("NEWS.setView('scroll')")
    page.wait_for_timeout(300)
    page.evaluate(SWIPE, [312, 78, 400, 410])          # 다음
    nxt = page.evaluate(f"({{cur: NEWS.state().current, sheets: {SHEETS}, faces: document.querySelectorAll('#book .sheet .sheet-face').length}})")
    page.wait_for_timeout(200)
    turning = page.evaluate("getComputedStyle(document.querySelector('#book .sheet-face')).transform")
    page.wait_for_timeout(500)
    gone = page.evaluate(SHEETS)
    page.evaluate(SWIPE, [78, 312, 400, 400])          # 이전: 옛 화면을 깔고 앞 쪽이 덮으며
    prv = page.evaluate(f"({{cur: NEWS.state().current, faces: document.querySelectorAll('#book .sheet .sheet-face').length}})")
    for _ in range(3):                                 # 연달아 넘겨도 덮개는 하나
        page.evaluate("NEWS.go(1)")
    rapid = page.evaluate(SHEETS)
    page.wait_for_timeout(700)
    after = page.evaluate(f"({{cur: NEWS.state().current, sheets: {SHEETS}}})")
    page.evaluate("NEWS.setZoom(2)")                  # 확대 중엔 덮개 없이
    page.evaluate("NEWS.go(1)")
    zoomed = page.evaluate(SHEETS)
    ctx.close()
    assert nxt == {"cur": 1, "sheets": 1, "faces": 1}
    assert turning not in ("none", "matrix(1, 0, 0, 1, 0, 0)")   # 도는 중
    assert gone == 0
    assert prv == {"cur": 0, "faces": 2}
    assert rapid == 1
    assert after == {"cur": 3, "sheets": 0}
    assert zoomed == 0
    assert not errors, errors


def test_scroll_view_turn_screenshot(browser, tmp_path):  # noqa: F811
    """넘어가는 중간 모습 (실제 화면 확인용 캡처: build/s32-turn.png)."""
    from pathlib import Path
    index = make_site(tmp_path)
    ctx, page, _ = open_page(browser, index, 390, 844)
    page.evaluate("NEWS.setView('scroll')")
    page.wait_for_timeout(300)
    page.evaluate("NEWS.go(1)")
    page.wait_for_timeout(230)
    out = Path(__file__).resolve().parent.parent / "build" / "s32-turn.png"
    out.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(out))
    ctx.close()
    assert out.stat().st_size > 0
