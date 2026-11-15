"""S49 화면 (시안 B): 부제 한 줄, 종합면 각도 칸·묶음 띠·둘째 이슈 묶음.

기준 (project-plan.md S49d)
- 부제(있을 때) 뉴스 면 기사에, 단신 한 줄 목록엔 없음, 부제가 있으면 기본 리드 한 줄 줄임
- 종합면: 메인 첫 기사만 각도 칸 없음, 띠 건수 = 실린 수, 둘째 묶음은 띠 기사가 안 실리면 통째로 빠짐, 묶음 안 순서 유지, 창에 띠·각도 칸 없음
- 1180×820·1366×1024·390×844(어둡게): 30쪽, 넘친 쪽 0. 패드 두 크기에서 둘째 묶음이 실림, 종합면 80% 이상
- 부제를 넣어도 단신으로 내려간 기사 수가 늘지 않음 (부제 없는 같은 견본과 견줌)
"""
import pytest

from pipeline.render import jonghap_hosts
from pipeline.settings import load_config, load_sources
from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)
from tests.test_s47_browser import _with_angles

SIZES = [(1180, 820), (1366, 1024), (390, 844)]
ANG = ("경위", "시장 반응", "인물", "후임", "전망", "정책", "현장", "쟁점")


def _site(decks=True, plan=True, long=True):
    def mutate(ed):
        for n, it in enumerate(i for v in ed["sections"].values() for i in v):
            if long:
                for a in it["articles"]:
                    a["lang"] = "en"
                it.setdefault("llm", {})["ko_summary"] = f"{n}번 기사의 AI 요약 문장입니다. " * 30
                it["llm"]["ko_title"] = f"{n}번 기사 한국어 제목"
            if decks:   # 예비 기사도 — 종합면 후보는 예비 기사에서 온다
                it.setdefault("llm", {})["deck"] = f"{n}번 부제 핵심 사실 한 줄"
        _with_angles(6)(ed)
        if plan:
            cfg, src = load_config(), load_sources()
            lead, second, _ = jonghap_hosts([(s.id, ed["sections"].get(s.id, [])) for s in cfg.sections], {s.name: s.country for s in src.sources})
            groups = [{"host": lead["issue_id"], "band": "젠슨 황 사임 후폭풍",
                       "angles": {a["issue_id"]: {"angle": ANG[k % len(ANG)], "dup": False, "dup_of": None} for k, a in enumerate(lead["angles"][:8])}}]
            if second is None:   # 견본 1면에 조건 맞는 둘째 이슈가 없으면 만든다 (후보 2건, 메인 후보와 겹치지 않게)
                second = next(r for r in ed["sections"]["front"] if r is not lead)
                rest = [b for b in ed["sections"]["briefs"] if b.get("reserve") and b["issue_id"] not in {a["issue_id"] for a in lead["angles"]}]
                second["angles"] = [dict(x) for x in rest[:3]]
                second["title"] = "충청 메가프로젝트 착공 현장"
            groups.append({"host": second["issue_id"], "band": "충청 메가프로젝트",
                           "angles": {a["issue_id"]: {"angle": ANG[(k + 3) % len(ANG)], "dup": False, "dup_of": None} for k, a in enumerate(second["angles"][:8])}})
            ed["jonghap_plan"] = {"lead": lead["issue_id"], "groups": groups}
    return mutate


JH = """() => { const ps = [...document.querySelectorAll('#book .leaf > .page.sec-jonghap')];
  const items = ps.flatMap(p => [...p.querySelectorAll('.page-inner > .item')]);
  const fill = ps.map(p => { const inn = p.querySelector('.page-inner'), r = inn.getBoundingClientRect(); let b = r.top;
    [...inn.children].forEach(c => { const q = c.getBoundingClientRect(); if (q.height > 0) b = Math.max(b, q.bottom); }); return (b - r.top) / r.height; });
  return { fill, ids: items.map(x => x.getAttribute('data-issue')), groups: items.map(x => x.getAttribute('data-jh-group')),
    angled: items.map(x => !!x.querySelector(':scope > .jh-angle')), band: items.map(x => !!x.querySelector('.jh-band')),
    theme: (ps[0] && ps[0].querySelector('.jh-theme') || {}).textContent || '',
    bandText: (ps.map(p => p.querySelector('.jh-band')).find(Boolean) || {}).textContent || '',
    flow: [...document.querySelectorAll('#flow section[data-section=jonghap] > .item')].map(x => x.getAttribute('data-issue')),
    decks: document.querySelectorAll('#book .leaf > .page:not(.sec-briefs) .item .deck').length,
    briefDecks: [...document.querySelectorAll('#book .leaf > .page.sec-briefs .bt-row .deck')].filter(d => d.offsetHeight > 0).length,
    clamp: (() => { const l = document.querySelector('#book .leaf > .page:not(.sec-front):not(.sec-jonghap) .item.has-deck:not(.roomy):not(.compact):not(.tight) .lead');
                    return l ? getComputedStyle(l).webkitLineClamp : null; })() }; }"""


@pytest.mark.parametrize("w,h", SIZES)
def test_jonghap_angles_bands_and_decks(browser, tmp_path, w, h):
    index = make_site(tmp_path, mutate=_site())
    ctx, page, errors = open_page(browser, index, w, h)
    if w < 500:
        page.emulate_media(color_scheme="dark")
    st = page.evaluate("() => NEWS.state()")
    m = page.evaluate(JH)
    assert not errors, errors
    assert st["pages"] == 30 and not st["overflow"], st
    # 종합면: 메인 첫 기사만 각도 칸 없음, 순서 유지, 띠 건수 = 실린 수
    assert m["ids"] and m["angled"][0] is False and all(m["angled"][1:]), m
    assert m["ids"] == [i for i in m["flow"] if i in m["ids"]], m          # 묶음 안·사이 순서 그대로
    n0, n1 = m["groups"].count("0"), m["groups"].count("1")
    assert m["theme"] == f"젠슨 황 사임 후폭풍 · 기사 {n0}건", m
    if n1:
        assert m["band"][m["groups"].index("1")] and m["bandText"] == f"충청 메가프로젝트 · 기사 {n1}건", m
    else:
        assert not any(m["band"]), m                                         # 둘째 묶음이 빠지면 띠도 없음
    if w >= 1000:
        assert n1 >= 2, m                                                    # 패드에서는 둘째 묶음이 실린다
        assert min(m["fill"]) >= 0.8, m["fill"]
    # 부제: 뉴스 면 기사에 있고 단신 한 줄엔 없음, 부제 있는 기사의 기본 리드는 3줄
    assert m["decks"] > 10 and m["briefDecks"] == 0, m
    assert m["clamp"] == "3", m
    # 창: 부제 + 전체 요약, 띠·각도 칸은 숨김
    page.evaluate("(i) => NEWS.goTo(i)", int(page.locator("#book .leaf > .page.sec-jonghap").first.get_attribute("data-page")))
    page.wait_for_timeout(500)
    target = m["ids"][m["groups"].index("1")] if n1 else m["ids"][-1]   # 띠가 있는 기사를 열어 띠가 숨는지 본다
    page.evaluate("(id) => NEWS.openReader(id)", target)
    page.wait_for_selector("#reader:not([hidden]) .reader-body .item")
    r = page.evaluate("""() => { const b = document.querySelector('#reader .reader-body');
      const vis = s => [...b.querySelectorAll(s)].some(e => e.offsetHeight > 0);
      const l = b.querySelector('.lead');
      return { deck: vis('.deck'), band: vis('.jh-band'), angle: vis('.jh-angle'), clamp: l && getComputedStyle(l).webkitLineClamp }; }""")
    assert r == {"deck": True, "band": False, "angle": False, "clamp": "none"}, r
    ctx.close()


@pytest.mark.parametrize("w,h", SIZES)
def test_decks_do_not_push_more_articles_to_briefs(browser, tmp_path, w, h):
    """부제 없는 같은 견본(S48 꼴)과 견줌 — 짧은 요약·계획 없음, 긴 요약·계획 있음 두 가지."""
    for plan, long in ((False, False), (True, True)):
        got = {}
        for decks in (False, True):
            index = make_site(tmp_path / f"{plan}{decks}", mutate=_site(decks=decks, plan=plan, long=long))
            ctx, page, errors = open_page(browser, index, w, h)
            st = page.evaluate("() => NEWS.state()")
            ctx.close()
            assert not errors and st["pages"] == 30 and not st["overflow"], st
            got[decks] = st["demoted"]
        assert got[True] <= got[False], (plan, got)


def test_no_plan_short_summaries_still_fit(browser, tmp_path):
    """계획 없는 견본(S47 방식)·짧은 요약도 30쪽·넘침 0, 각도 칸·띠 없음."""
    for w, h in SIZES:
        index = make_site(tmp_path / f"{w}", mutate=_site(decks=True, plan=False, long=False))
        ctx, page, errors = open_page(browser, index, w, h)
        st = page.evaluate("() => NEWS.state()")
        m = page.evaluate(JH)
        ctx.close()
        assert not errors and st["pages"] == 30 and not st["overflow"], (w, st)
        assert not any(m["angled"]) and not any(m["band"]) and "· 기사" not in m["theme"], m
