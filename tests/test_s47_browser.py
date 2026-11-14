"""S47 화면: 종합면(시안 A)·단신 접기(시안 B).

기준 (project-plan.md S47c·d):
- 1면 바로 다음에 "종합" — 메인 이슈 제목 띠와 기사 3~6건, 넘쳐도 단신으로 안 내려감. 종합면 없는 날은 쪽 순서가 그대로
- 단신은 1쪽: 분야 탭(전체·분야별 건수) + 고른 탭의 위 10건, "모두 보기" 창에 전체(건수 맞음)
- 다른 면에서 내려온 기사가 더 읽을 기사·단신 앞에, 남는 쪽은 더 읽을 기사 → 끝 안내 쪽. 총 30쪽 고정, 넘친 쪽 없음
- 휴대폰 너비·어두운 화면에서도
"""
import pytest

from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)

SIZES = [(1180, 820), (390, 844)]


def _with_angles(n):
    """뉴스 면 기사마다 예비 기사 n 건을 종합면 후보로 (서로 다른 매체)."""
    def mutate(ed):
        seen, pick = set(), []
        for b in ed["sections"]["briefs"]:
            if b.get("reserve") and b["source"] not in seen:
                seen.add(b["source"])
                pick.append(b)
        for k in ("front", "politics", "economy", "international", "society", "interest"):
            for it in ed["sections"].get(k, []):
                it["angles"] = [p for p in pick if p["source"] != it["source"]][:n]
    return mutate


STATE = """() => { const st = NEWS.state(); const pages = [...document.querySelectorAll('#book .page, .page')].filter((p, i, a) => a.indexOf(p) === i);
  return { pages: st.pages, overflow: st.overflow.length, briefs: st.briefs,
    order: [...new Set([...document.querySelectorAll('.page')].map(p => (p.className.match(/sec-(\\w+)/) || [])[1]))],
    jh: document.querySelectorAll('.page.sec-jonghap article.item').length,
    theme: (document.querySelector('.page.sec-jonghap .jh-theme') || {}).textContent || '',
    briefPages: new Set([...document.querySelectorAll('.page.sec-briefs')].map(p => p.getAttribute('data-page'))).size,
    tabs: [...document.querySelectorAll('.page.sec-briefs .bt-tab')].map(b => b.textContent),
    rows: document.querySelectorAll('.page.sec-briefs .bt-list:not([hidden]) .bt-row').length } }"""


@pytest.mark.parametrize("w,h", SIZES)
def test_jonghap_and_folded_briefs(browser, tmp_path, w, h):
    index = make_site(tmp_path, mutate=_with_angles(5))
    ctx, page, errors = open_page(browser, index, w, h)
    if w < 500:
        page.emulate_media(color_scheme="dark")
    m = page.evaluate(STATE)
    assert not errors, errors
    assert m["pages"] == 30 and m["overflow"] == 0, m
    assert m["order"][:2] == ["front", "jonghap"], m["order"]
    assert 3 <= m["jh"] <= 6 and m["theme"], m
    assert m["briefPages"] == 1 and m["tabs"][0].startswith("전체 ")
    total = int(m["tabs"][0].split()[-1])
    assert total == m["briefs"] and 0 < m["rows"] <= total   # S48: 건수는 쪽에 들어가는 만큼 (test_s48_browser)
    assert sum(int(t.split()[-1]) for t in m["tabs"][1:]) == total   # 분야 탭 건수 합 = 전체
    # 분야 탭 → 그 분야만
    tab = page.locator(".page.sec-briefs .bt-tab").nth(1)
    name = " ".join(tab.text_content().split()[:-1])
    page.evaluate("(i) => NEWS.goTo(i)", int(page.locator(".page.sec-briefs").first.get_attribute("data-page")))
    page.wait_for_timeout(600)
    page.locator(".page.sec-briefs .bt-tab:visible").nth(1).click()
    vis = page.locator(".page.sec-briefs .bt-list:not([hidden])").first
    assert vis.get_attribute("data-bt-list") != "all" and vis.locator(".bt-row").count() <= int(tab.text_content().split()[-1])
    # 키보드: 탭 목록 안은 화살표로 (roving tabindex)
    first = page.locator(".page.sec-briefs .bt-tab:visible").first
    first.focus()
    page.keyboard.press("ArrowRight")
    assert page.evaluate("() => document.activeElement.getAttribute('aria-selected')") == "true"
    assert page.evaluate("() => [...document.activeElement.parentNode.children].filter(b => b.tabIndex === 0).length") == 1
    # 전체 보기 단추는 탭마다 (S48) — 창·돌아가기는 단신이 많은 test_s48_browser 에서
    page.locator(".page.sec-briefs .bt-tab:visible").first.click()
    btn = page.locator(".page.sec-briefs .bt-all:visible")
    assert btn.count() == 1 and btn.is_disabled() == (m["rows"] == total), (btn.text_content(), m)
    ctx.close()


def test_no_jonghap_keeps_order(browser, tmp_path):
    """후보가 2건뿐이면 종합면 없음 — 1면 다음은 지금처럼 정치면, 쪽 수는 그대로."""
    index = make_site(tmp_path, mutate=_with_angles(2))
    ctx, page, errors = open_page(browser, index, 1180, 820)
    m = page.evaluate(STATE)
    ctx.close()
    assert not errors, errors
    assert "jonghap" not in m["order"] and m["order"][1] == "politics"
    assert m["pages"] == 30 and m["overflow"] == 0
