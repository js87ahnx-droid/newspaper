"""S56 자세히 창 위 막대: 요약·전문 탭과 닫기를 한 줄에, 스크롤해도 위에 고정. 가짜 중계 서버(reader.test)."""
from __future__ import annotations

import os

import pytest

from tests.test_reader import ARTICLE, _open
from tests.test_render_browser import browser  # noqa: F401  (픽스처)
from tests.test_s54_browser import _open_title

BAR = """() => { const p = document.querySelector('#reader .reader-panel').getBoundingClientRect();
  const c = document.querySelector('#reader .reader-close').getBoundingClientRect();
  const t = document.querySelector('#reader .sw-tabs'), tr = t && t.getBoundingClientRect();
  const tab = t && t.querySelector('.sw-tab:last-child').getBoundingClientRect();
  const hit = document.elementFromPoint(c.left + c.width / 2, c.top + c.height / 2);
  return { pTop: p.top, pRight: p.right, cTop: c.top, cMid: c.top + c.height / 2, cRight: c.right, cLeft: c.left,
           tTop: tr && tr.top, tMid: tr && (tr.top + tr.bottom) / 2, tBottom: tr && tr.bottom, tabRight: tab && tab.right,
           closeOnTop: !!(hit && hit.closest('[data-reader-close]')) }; }"""


@pytest.mark.parametrize("w,h", [(390, 844), (1180, 820)])
def test_tabs_and_close_one_bar_stays_on_top(browser, tmp_path, monkeypatch, w, h):
    art = dict(ARTICLE, paragraphs=["긴 문단입니다. " * 60] * 12)
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, art))
    page.set_viewport_size({"width": w, "height": h})
    page.wait_for_timeout(400)
    _open_title(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_selector("#reader .ft .rv-p")
    page.evaluate("() => document.querySelectorAll('#reader .sw-tab')[1].click()")
    page.wait_for_timeout(600)
    shot = os.environ.get("S56_SHOTS")
    for k, top in enumerate([0, 3000]):
        page.evaluate("(y) => { document.querySelector('#reader .reader-panel').scrollTop = y; }", top)
        page.wait_for_timeout(150)
        if shot:
            page.screenshot(path=os.path.join(shot, f"bar-{w}-{k}.png"))
        r = page.evaluate(BAR)
        assert abs(r["tTop"] - r["pTop"]) <= 2, r                       # 탭 줄은 창 맨 위에
        assert abs(r["cMid"] - r["tMid"]) <= 6, r                       # 닫기는 탭 줄과 같은 줄
        assert r["cTop"] >= r["pTop"] and r["cRight"] <= r["pRight"], r
        assert r["tabRight"] <= r["cLeft"], r                            # 전문 탭과 닫기가 겹치지 않음
        assert r["closeOnTop"], r                                        # 닫기가 아래 글에 가리지 않음
    assert page.evaluate("() => document.querySelector('#reader .reader-panel').scrollTop") > 500
    page.evaluate("() => document.querySelector('[data-reader-close]').click()")
    assert page.evaluate("() => document.getElementById('reader').hidden")
    assert not errors, errors
    ctx.close()


def test_close_stays_on_top_without_tabs(browser, tmp_path, monkeypatch):
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE), configured=False)
    page.set_viewport_size({"width": 390, "height": 500})
    page.wait_for_timeout(400)
    page.evaluate("() => NEWS.openReader(document.querySelector('#flow article.item').getAttribute('data-issue'))")
    page.wait_for_timeout(200)
    assert page.evaluate("() => !document.querySelector('#reader .sw-tabs')")
    page.evaluate("() => { document.querySelector('#reader .reader-panel').scrollTop = 4000; }")
    page.wait_for_timeout(100)
    r = page.evaluate(BAR)
    assert r["cTop"] >= r["pTop"] and r["cTop"] - r["pTop"] < 30 and r["closeOnTop"], r
    assert not errors, errors
    ctx.close()
