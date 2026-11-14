"""S48 기기별 빈자리 줄이기 (2026-11-14 사용자 요청).

기준 (project-plan.md S48):
- 단신 탭 쪽: 탭마다 쪽에 들어가는 만큼(10건 상한 없음) — 단신이 많으면 패드·휴대폰 모두 15건 넘게, 넘친 쪽 없음
- 탭마다 "○○ 전체 보기" 단추 하나: 누르면 그 탭 목록만 창에(건수 맞음), 다 보인 탭은 단추가 꺼지고 눌러도 창이 안 열림
- 면 안에서 덜 찬 쪽은 앞 쪽 기사를 넘겨 받아 채움: 종합면 두 쪽 모두 80% 이상, 기사 순서는 원본 그대로
- 자세히 창은 지면에서 줄인 요약이 아니라 전체 요약 (AI 요약은 render 에서 자르지 않음)
"""
import copy

import pytest

from pipeline.render import _display
from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)
from tests.test_s47_browser import _with_angles

SIZES = [(1180, 820), (390, 844)]


def _many_briefs(times):
    def mutate(ed):
        _with_angles(5)(ed)
        base = [b for b in ed["sections"]["briefs"] if not b.get("reserve")]
        small = base[-1]["topic"]   # 이 분야만 늘리지 않는다 — "다 보인 탭"(단추 꺼짐)도 시험하게
        base = [b for b in base if b["topic"] != small]
        for r in range(times):
            for b in base:
                c = copy.deepcopy(b)
                c["issue_id"] = f'{b["issue_id"]}-x{r}'
                c["url"] = f'{b["url"]}?x={r}'
                ed["sections"]["briefs"].append(c)
    return mutate


TABS = """() => [...document.querySelectorAll('#book .leaf > .page.sec-briefs .bt-tab')].map(t => {
  const key = t.getAttribute('data-bt'), box = t.closest('.btabs');
  const ol = box.querySelector('[data-bt-list="' + key + '"]'), btn = box.querySelectorAll('[data-bt-all="' + key + '"]');
  return { key, n: +t.textContent.split(' ').pop(), rows: ol.children.length, btns: btn.length, off: btn[0] && btn[0].disabled }; })"""


@pytest.mark.parametrize("w,h", SIZES)
def test_brief_tabs_fill_page_and_per_tab_all(browser, tmp_path, w, h):
    index = make_site(tmp_path, mutate=_many_briefs(8))
    ctx, page, errors = open_page(browser, index, w, h)
    st = page.evaluate("() => NEWS.state()")
    assert not errors, errors
    assert st["pages"] == 30 and not st["overflow"], st
    tabs = page.evaluate(TABS)
    assert tabs[0]["key"] == "all" and tabs[0]["rows"] >= 15, tabs   # 예전 10건 상한 없음
    for t in tabs:
        assert t["btns"] == 1 and 0 < t["rows"] <= t["n"], t
        assert t["off"] == (t["rows"] == t["n"]), t                    # 다 보였으면 꺼짐
    page.evaluate("(i) => NEWS.goTo(i)", int(page.locator("#book .leaf > .page.sec-briefs").first.get_attribute("data-page")))
    page.wait_for_timeout(600)
    # 분야 탭의 전체 보기 → 그 분야만
    topic = next((t for t in tabs[1:] if not t["off"]), None)
    full = next((t for t in tabs if t["off"]), None)
    assert topic and full, tabs   # 한 분야는 안 늘려 두 크기 모두 "다 안 보인 분야"와 "다 보인 분야"가 있다 — 아래 확인이 건너뛰지 않게
    if topic:
        page.locator(f'#book .leaf > .page.sec-briefs [data-bt="{topic["key"]}"]').click()
        page.locator("#book .leaf > .page.sec-briefs .bt-all:visible").click()
        page.wait_for_selector("#reader:not([hidden]) .bt-full")
        assert page.locator("#reader .bt-full .item.brief").count() == topic["n"]
        assert page.locator("#reader .bt-full .brief-topic").count() == 1
        page.locator("#reader .bt-full .item.brief .hl a").first.click()
        page.wait_for_selector("#reader .rv-back")
        lead = page.evaluate("() => { const l = document.querySelector('#reader .reader-body .lead'); return l && [getComputedStyle(l).webkitLineClamp, l.scrollHeight <= l.clientHeight + 1]; }")
        assert lead and lead[0] == "none" and lead[1], lead   # 자세히 창 요약은 줄 제한 없음
        page.locator("#reader .rv-back").click()
        assert page.locator("#reader .bt-full .item.brief").count() == topic["n"]
        assert page.locator("#reader").get_attribute("aria-label").startswith(page.locator("#reader .bt-full-h").text_content())
        page.locator("[data-reader-close]").click()
    # 전체 탭 → 모두
    page.locator('#book .leaf > .page.sec-briefs [data-bt="all"]').click()
    page.locator("#book .leaf > .page.sec-briefs .bt-all:visible").click()
    page.wait_for_selector("#reader:not([hidden]) .bt-full")
    assert page.locator("#reader .bt-full .item.brief").count() == tabs[0]["n"]
    page.locator("[data-reader-close]").click()
    # 다 보인 탭: 단추가 꺼져 창이 안 열림
    if full:
        page.locator(f'#book .leaf > .page.sec-briefs [data-bt="{full["key"]}"]').click()
        page.locator("#book .leaf > .page.sec-briefs .bt-all:visible").click(force=True)
        page.wait_for_timeout(200)
        assert page.locator("#reader").is_hidden()
    ctx.close()


FILL = """() => [...document.querySelectorAll('#book .leaf > .page')].map(p => {
  const inn = p.querySelector('.page-inner'), r = inn.getBoundingClientRect(); let b = r.top;
  [...inn.children].forEach(c => { const q = c.getBoundingClientRect(); if (q.height > 0) b = Math.max(b, q.bottom); });
  return { sec: (p.className.match(/sec-(\\w+)/) || [])[1], fill: (b - r.top) / r.height,
           ids: [...inn.querySelectorAll(':scope > .item')].map(x => x.getAttribute('data-issue')) }; })"""


def _long_summaries(ed):
    """실제 호처럼 AI 요약이 긴 지면 (견본 리드 300자만으로는 기사 5건이 두 쪽을 못 채움 — 기사 길이 문제이지 배치 문제가 아님)."""
    for n, it in enumerate(i for v in ed["sections"].values() for i in v):   # 종합면 기사는 단신 후보에서 오므로 단신까지
        for a in it["articles"]:
            a["lang"] = "en"   # 영어 기사: 원 제목 + AI 요약 (interests.yaml)
        it.setdefault("llm", {})["ko_summary"] = f"{n}번 기사의 AI 요약 문장입니다. " * 30
    _with_angles(5)(ed)


@pytest.mark.parametrize("w,h", [(1180, 820), (1366, 1024), (390, 844)])
def test_section_pages_balanced(browser, tmp_path, w, h):
    index = make_site(tmp_path, mutate=_long_summaries)
    ctx, page, errors = open_page(browser, index, w, h)
    pages = page.evaluate(FILL)
    flow = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#flow section.sec')].map(s =>
        [s.getAttribute('data-section'), [...s.children].map(x => x.getAttribute('data-issue')).filter(Boolean)]))""")
    st = page.evaluate("() => NEWS.state()")
    ctx.close()
    assert not errors, errors
    assert not st["overflow"] and st["pages"] == 30, st
    jh =[p for p in pages if p["sec"] == "jonghap"]
    assert jh and min(p["fill"] for p in jh) >= 0.8, [round(p["fill"], 2) for p in jh]
    for sec in ("jonghap", "politics", "economy", "international", "society"):   # 넘겨 받아도 순서 그대로
        ids = [i for p in pages if p["sec"] == sec for i in p["ids"]]
        own = [i for i in ids if i in flow.get(sec, [])]
        assert own == [i for i in flow.get(sec, []) if i in own], sec


def test_ai_summary_not_capped():
    long = "가" * 900
    item = {"title": "Title", "lead": "feed " * 200,
            "articles": [{"title": "Title", "lang": "en", "source": "X"}], "llm": {"ko_summary": long}}

    class D:
        english, other = "original_with_ko_summary", "translated_title"
    v = _display(item, D)
    assert v["lead"] == long and v["lead_note"] == "AI 요약"
    item["llm"] = {}
    assert len(_display(item, D)["lead"]) <= 300   # 피드 리드는 그대로 상한
