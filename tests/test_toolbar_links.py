"""도구 줄의 "오늘 호" 링크 (2026-11-03 사용자 요청: 지난 호 보기 옆에 오늘 호 보기).

- 지난 호 지면(archive/<날짜>/)에는 "지난 호" 바로 뒤에 맨 앞(오늘 호)으로 가는 링크
- 오늘 호(맨 앞 index.html)에는 자기 자신이라 없음
- 휴대폰 폭에서도 도구 줄이 넘치지 않는다
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
    return re.findall(r'<a class="tb-link" href="([^"]*)">([^<]+)</a>', bar)


def test_today_link_only_on_past_editions(tmp_path):
    ed = _edition(tmp_path)
    cfg, interests, sources = load_config(), load_interests(), load_sources()
    today = _links(render_html(ed, cfg, interests, sources, base=""))
    past = _links(render_html(ed, cfg, interests, sources, base="../../"))
    assert today == [("archive/", "지난 호")]
    assert past == [("../../archive/", "지난 호"), ("../../", "오늘 호")]


@pytest.mark.parametrize("w", [390, 375])
def test_toolbar_fits_on_phone_with_today_link(browser, tmp_path, w):  # noqa: F811
    ed = _edition(tmp_path)
    site = tmp_path / "site"
    arch = site / "archive" / ed["edition"]
    arch.mkdir(parents=True)
    (arch / "index.html").write_text(render_html(ed, load_config(), load_interests(), load_sources(), base="../../"), encoding="utf-8")
    ctx, page, errors = open_page(browser, arch / "index.html", w, 844)
    m = page.evaluate("""() => { const t = document.getElementById('toolbar'), a = [...t.querySelectorAll('.tb-link')];
        return {over: t.scrollWidth - t.clientWidth, page: document.documentElement.scrollWidth - innerWidth,
                links: a.map(x => x.textContent), vis: a.every(x => x.getBoundingClientRect().width > 0)}; }""")
    # file:// 에서는 폴더 주소가 index.html 로 안 열려(Pages 에서는 열림) 누르지 않고 가리키는 곳만 본다
    landed = page.evaluate("document.querySelectorAll('#toolbar .tb-link')[1].href")
    ctx.close()
    assert m["links"] == ["지난 호", "오늘 호"] and m["vis"]
    assert m["over"] <= 1 and m["page"] <= 1, m
    assert landed.endswith("/site/"), landed       # archive/<날짜>/ 에서 두 단계 위 = 오늘 호
    assert not errors, errors
