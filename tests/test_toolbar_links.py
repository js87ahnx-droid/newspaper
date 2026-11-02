"""도구 줄의 호 이동 단추 (2026-11-03 사용자 요청: 지난 호 옆에 오늘 호 → 시안 A "목록 / 오늘" 상자 단추).

- 모든 지면에 [목록](지난 호 목록) [오늘](맨 앞 오늘 호) — 다른 단추와 같은 상자
- 오늘 호에서는 "오늘"이 눌린 모양(aria-current)
- 휴대폰 폭에서도 도구 줄이 넘치지 않는다 (오늘 호·지난 호 둘 다)
"""
import re

import pytest

from pipeline.render import render_html
from pipeline.settings import load_config, load_interests, load_sources
from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)


def _edition(tmp_path):
    got = {}
    make_site(tmp_path, mutate=lambda out: got.setdefault("ed", out))
    return got["ed"]


def _links(html):
    bar = html[html.index('<div id="toolbar"'):html.index("</div>", html.index('<div id="toolbar"'))]
    return [(h, t, "aria-current" in rest) for c, h, rest, t in
            re.findall(r'<a class="tb-link tb-btn( on)?" href="([^"]*)"([^>]*)>([^<]+)</a>', bar)]


def test_today_link_only_on_past_editions(tmp_path):
    ed = _edition(tmp_path)
    cfg, interests, sources = load_config(), load_interests(), load_sources()
    today = _links(render_html(ed, cfg, interests, sources, base=""))
    past = _links(render_html(ed, cfg, interests, sources, base="../../"))
    assert today == [("archive/", "목록", False), ("./", "오늘", True)]
    assert past == [("../../archive/", "목록", False), ("../../", "오늘", False)]


@pytest.mark.parametrize("w,past", [(390, True), (375, True), (390, False), (375, False)])
def test_toolbar_fits_on_phone_with_today_link(browser, tmp_path, w, past):  # noqa: F811
    ed = _edition(tmp_path)
    site = tmp_path / "site"
    arch = site / "archive" / ed["edition"]
    arch.mkdir(parents=True)
    (arch / "index.html").write_text(render_html(ed, load_config(), load_interests(), load_sources(), base="../../"), encoding="utf-8")
    if not past:
        (site / "index.html").write_text(render_html(ed, load_config(), load_interests(), load_sources(), base=""), encoding="utf-8")
    ctx, page, errors = open_page(browser, arch / "index.html" if past else site / "index.html", w, 844)
    m = page.evaluate("""() => { const t = document.getElementById('toolbar'), a = [...t.querySelectorAll('.tb-link')];
        return {over: t.scrollWidth - t.clientWidth, page: document.documentElement.scrollWidth - innerWidth,
                links: a.map(x => x.textContent), vis: a.every(x => x.getBoundingClientRect().width > 0),
                boxed: a.every(x => getComputedStyle(x).borderTopStyle === 'solid' && x.getBoundingClientRect().height >= 30),
                on: a.map(x => x.classList.contains('on'))}; }""")
    # file:// 에서는 폴더 주소가 index.html 로 안 열려(Pages 에서는 열림) 누르지 않고 가리키는 곳만 본다
    landed = page.evaluate("document.querySelectorAll('#toolbar .tb-link')[1].href")
    ctx.close()
    assert m["links"] == ["목록", "오늘"] and m["vis"] and m["boxed"], m
    assert m["on"] == [False, not past]
    assert m["over"] <= 1 and m["page"] <= 1, m
    assert landed.endswith("/site/"), landed       # 지난 호: archive/<날짜>/ 에서 두 단계 위 · 오늘 호: 자기 폴더
    assert not errors, errors
