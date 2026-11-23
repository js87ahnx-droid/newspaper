"""S59 화면: 기사 자세히 창·원문 창은 화면 2/3 아래로 작아지지 않고, 도구 막대는 위에 붙은 sticky 막대(높이 그대로)."""
from __future__ import annotations

from tests.test_reader import ARTICLE, _open
from tests.test_render_browser import browser  # noqa: F401  (픽스처)
from tests.test_s54_browser import _open_title

PANEL_H = "() => document.querySelector('#reader .reader-panel').getBoundingClientRect().height"


def test_short_reader_window_at_least_two_thirds(browser, tmp_path, monkeypatch):
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE))
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(400)
    tb = page.evaluate("() => { const t = document.getElementById('toolbar'), r = t.getBoundingClientRect(); return [getComputedStyle(t).position, r.top, r.height]; }")
    assert tb == ["sticky", 0, 44], tb                                  # 여백 없는 화면에서는 자리·높이 그대로
    _open_title(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_selector("#reader .ft .rv-p", state="attached")
    h0 = page.evaluate(PANEL_H)
    assert h0 >= 844 * 0.66 - 1 and h0 <= 844 - 32 + 1, h0
    page.evaluate("() => document.querySelectorAll('#reader .sw-tab')[1].click()")
    page.wait_for_timeout(400)
    assert abs(page.evaluate(PANEL_H) - h0) <= 1                         # 전문으로 넘겨도 같은 크기
    page.evaluate("() => document.querySelector('[data-reader-close]').click()")
    page.set_viewport_size({"width": 390, "height": 300})              # 화면이 작으면 화면 안에
    page.wait_for_timeout(300)
    _open_title(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_timeout(300)
    assert page.evaluate(PANEL_H) <= 300 - 32 + 1
    assert not errors, errors
    ctx.close()


def test_plain_reader_and_long_article(browser, tmp_path, monkeypatch):
    art = dict(ARTICLE, paragraphs=["긴 문단입니다. " * 60] * 12)
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, art), configured=False)
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(400)
    page.evaluate("() => NEWS.openReader(document.querySelector('#flow article.item').getAttribute('data-issue'))")
    page.wait_for_timeout(200)
    assert page.evaluate(PANEL_H) >= 844 * 0.66 - 1                     # 두 장 없는 창도
    assert page.evaluate(PANEL_H) <= 844 - 32 + 1
    assert not errors, errors
    ctx.close()
