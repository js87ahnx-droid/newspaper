"""S15 신문식 재배열 — 실제 브라우저로 측정.

기준 (project-plan.md S15):
- 모든 기사에 요약이 있다 / 입장 비교 이슈는 대표 기사 아래에 입장 차이 / 모든 기사에 날짜·시각
- iPad 4종 가로·세로 + 휴대폰 세로 2종에서 넘친 쪽 0
- 같은 화면 크기에서 호가 바뀌어도 쪽수가 같다 (쪽수 고정)
"""
import pytest

from pipeline.settings import load_config
from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)

SIZES = [(1024, 768), (1180, 820), (1194, 834), (1366, 1024), (820, 1180), (390, 844), (375, 812)]
STATE = "() => NEWS.state()"


def fixed_pages(w, h):
    total = sum(s.pages for s in load_config().sections)
    briefs = next(s.pages for s in load_config().sections if s.id == "briefs")
    return total + (briefs if w < 600 and w < h else 0)   # 휴대폰 세로는 단신 쪽 두 배


@pytest.mark.parametrize("w,h", SIZES)
def test_fixed_pages_no_overflow_every_item_has_summary_and_time(browser, tmp_path, w, h):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, w, h)
    st = page.evaluate(STATE)
    m = page.evaluate("""() => {
      const items = [...document.querySelectorAll('#book article.item[data-issue]')];
      return {
        n: items.length,
        noTime: items.filter(a => !a.querySelector('time.tm')).length,
        noLead: items.filter(a => !a.querySelector('.lead')).length,
        comparePages: document.querySelectorAll('#book .page.sec-compare').length,
        sw: document.scrollingElement.scrollWidth, iw: innerWidth };
    }""")
    ctx.close()
    assert not errors, errors
    assert st["pages"] == fixed_pages(w, h)
    assert st["overflow"] == [] and st["emptySummary"] == 0
    assert m["n"] >= 20 and m["noTime"] == 0 and m["noLead"] == 0
    assert m["comparePages"] == 0            # 입장 비교면 없음 (기사 아래로)
    assert m["sw"] <= m["iw"]


def test_page_count_same_across_editions(browser, tmp_path):  # noqa: F811
    """다른 날 호(기사·길이가 다름)도 같은 화면에서는 쪽수가 같다."""
    a = make_site(tmp_path / "a", edition_date="2026-10-16")
    b = make_site(tmp_path / "b", edition_date="2026-10-17", broken_photo=True)
    counts = []
    for index in (a, b):
        ctx, page, _ = open_page(browser, index, 1180, 820)
        counts.append(page.evaluate(STATE)["pages"])
        ctx.close()
    assert counts[0] == counts[1] == fixed_pages(1180, 820)


def test_compare_shown_under_representative_and_reader(browser, tmp_path):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, _ = open_page(browser, index, 1180, 820)
    cmp_ids = page.evaluate("[...document.querySelectorAll('#flow .cmp-inline')].map(c => c.closest('article').dataset.issue)")
    assert cmp_ids, "입장 차이가 붙은 기사가 없음"
    # 입장 차이는 그 기사 안(대표 기사 바로 아래)에 있다
    inside = page.evaluate("""() => [...document.querySelectorAll('#flow .cmp-inline')].every(c => {
        const art = c.closest('article.item'); return art && art.querySelector('.hl') && art.querySelector('.meta'); })""")
    assert inside
    # 자세히: 줄여 보인 기사도 원본 전체(입장 차이 포함)를 연다
    page.evaluate(f"NEWS.openReader('{cmp_ids[0]}')")
    r = page.evaluate("""() => ({ open: !document.getElementById('reader').hidden,
        cmp: !!document.querySelector('#reader .cmp-inline'), sub: !!document.querySelector('#reader .item.sub') })""")
    page.keyboard.press("Escape")
    closed = page.evaluate("document.getElementById('reader').hidden")
    ctx.close()
    assert r == {"open": True, "cmp": True, "sub": False} and closed


def test_demoted_items_become_briefs_in_score_order(browser, tmp_path):  # noqa: F811
    """정해진 쪽에 다 못 들어간 기사는 단신으로 내려가고, 내려간 기사는 단신 맨 앞(점수 순)."""
    index = make_site(tmp_path)
    ctx, page, _ = open_page(browser, index, 1024, 768)
    st = page.evaluate(STATE)
    order = page.evaluate("""() => [...document.querySelectorAll('#book .page.sec-briefs article.item.demoted')]
        .map(a => +(a.dataset.final2 || a.dataset.final))""")
    ctx.close()
    assert st["demoted"] == len(order)
    assert order == sorted(order, reverse=True)
