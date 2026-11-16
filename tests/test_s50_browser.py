"""S50 큐레이션 판 화면 (시안 B).

기준 (project-plan.md S50c·S50d)
- 1180×820·1366×1024·390×844(어둡게): 쪽 ≤ 24, 넘친 쪽 0, clip 0, dropped ≤ 기존 판, 예비 끌어오기 0, 더 읽을 기사에 예비 0
- 뉴스 면 기사 꼴 수 ≤ 정한 수, 목록 칸은 면 마지막, 목록 칸만 있는 쪽 0
- 지면에서 면 첫 기사 아닌 기사의 숨김 칸이 늘리기 뒤에도 안 보임, 리드 2줄. 기사 창에는 보임
- 목록 제목 → 그 기사 창. 분야를 내리면 그 분야 목록 줄이 지워지고 원본은 단신에
"""
import json

import pytest

from pipeline.render import masthead, render_html, write_assets
from pipeline.settings import load_config, load_interests, load_sources
from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)
from tests.test_s49_browser import _site
from tests.test_s50 import _edition

SIZES = [(1180, 820), (1366, 1024), (390, 844)]
KEEP = {"jonghap": 5, "politics": 4, "economy": 4, "international": 5, "society": 3, "interest": 5}


def _b_site(tmp_path, mutate=None):
    from datetime import date
    ed = _edition(mutate)
    cfg = load_config()
    site = tmp_path / "b"
    site.mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text(render_html(ed, cfg, load_interests(), load_sources(), base="", variant="b", alt_href="../"), encoding="utf-8")
    write_assets(site, masthead(date.fromisoformat(ed["edition"])))
    return site / "index.html"


M = """(keep) => {
  const pages = [...document.querySelectorAll('#book .leaf > .page')];
  const bySec = {};
  pages.forEach(p => { const sec = [...p.classList].find(c => c.startsWith('sec-')); if (!sec) return;
    (bySec[sec.slice(4)] = bySec[sec.slice(4)] || []).push(p); });
  const counts = {}, listLast = {}, listOnly = [];
  Object.keys(keep).forEach(id => { const ps = bySec[id] || [];
    counts[id] = ps.reduce((n, p) => n + p.querySelectorAll('.page-inner > article.item').length, 0);
    const kids = ps.flatMap(p => [...p.querySelector('.page-inner').children].filter(c => c.matches('article.item, .more-list')));
    listLast[id] = !kids.some(c => c.matches('.more-list')) || kids[kids.length - 1].matches('.more-list');
    ps.forEach(p => { const inn = p.querySelector('.page-inner');
      if (inn.querySelector(':scope > .more-list') && !inn.querySelector(':scope > article.item')) listOnly.push(id); }); });
  const vis = el => el && el.offsetHeight > 0 && getComputedStyle(el).display !== 'none';
  const nonHead = [...document.querySelectorAll('#book .page-inner > article.item:not(.sec-head):not(.brief):not(.fz)')];
  const hide = ['.orig', '.flow', '.rel-arts', '.op-rel', '.why', '.meta .tm', '.meta .days', '.meta .cover', '.meta .note', '.meta .link-btn', '.cmp-inline', '.an-views', '.an-pts'];
  const shown = nonHead.flatMap(it => hide.filter(s => [...it.querySelectorAll(s)].some(vis)).map(s => it.getAttribute('data-issue') + s));
  const clamps = nonHead.map(it => it.querySelector('.lead')).filter(vis).map(l => getComputedStyle(l).webkitLineClamp);
  return { counts, listLast, listOnly, shown, clamps, nonHead: nonHead.length,
    lists: document.querySelectorAll('#book .page-inner > .more-list').length,
    pulled: document.querySelectorAll('#book [data-pulled]').length,
    moreReserve: document.querySelectorAll('#book .page.sec-more .item[data-reserve="1"]').length,
    tbVar: (document.querySelector('#toolbar .tb-var') || {}).textContent }; }"""


@pytest.mark.parametrize("w,h", SIZES)
def test_curated_layout(browser, tmp_path, w, h):
    base = make_site(tmp_path / "a", mutate=_site())
    ctx, page, errors = open_page(browser, base, w, h)
    st_a = page.evaluate("() => NEWS.state()")
    ctx.close()
    index = _b_site(tmp_path, _site())
    ctx, page, errors = open_page(browser, index, w, h)
    if w < 500:
        page.emulate_media(color_scheme="dark")
    st = page.evaluate("() => NEWS.state()")
    m = page.evaluate(M, KEEP)
    assert not errors, errors
    assert st["pages"] <= 24 and st["pages"] < st_a["pages"] and not st["overflow"] and st["clipped"] == 0, st
    assert st["dropped"] <= st_a["dropped"], (st["dropped"], st_a["dropped"])
    assert all(m["counts"][k] <= KEEP[k] for k in KEEP), m["counts"]
    assert all(m["listLast"].values()) and not m["listOnly"], m
    assert m["lists"] >= 3 and m["pulled"] == 0 and m["moreReserve"] == 0, m
    assert m["nonHead"] > 5 and not m["shown"], m["shown"][:10]
    assert m["clamps"] and set(m["clamps"]) == {"2"}, m["clamps"]
    assert m["tbVar"] == "기존 판"
    ctx.close()


def test_curated_reader_and_list_click(browser, tmp_path):
    index = _b_site(tmp_path, _site())
    ctx, page, errors = open_page(browser, index, 1180, 820)
    # 면 첫 기사 아닌 기사의 창: 지면에서 숨긴 원제목·점수가 보임
    iid = page.evaluate("() => document.querySelector('#book .page-inner > article.item.has-deck:not(.sec-head):not(.brief):not(.fz) .orig') ? document.querySelector('#book .page-inner > article.item.has-deck:not(.sec-head):not(.brief):not(.fz)').getAttribute('data-issue') : null")
    assert iid
    page.evaluate("(id) => NEWS.openReader(id)", iid)
    page.wait_for_selector("#reader:not([hidden]) .reader-body .item")
    r = page.evaluate("""() => { const b = document.querySelector('#reader .reader-body'); const v = s => [...b.querySelectorAll(s)].some(e => e.offsetHeight > 0);
      return { orig: v('.orig'), why: v('.why'), tm: v('.meta .tm') }; }""")
    assert r == {"orig": True, "why": True, "tm": True}, r
    page.evaluate("() => document.querySelector('[data-reader-close]').click()")
    # 목록 제목을 누르면 그 기사 창
    target = page.evaluate("""() => { const a = document.querySelector('#book .page-inner > .more-list a[data-open]');
      const i = +a.closest('.page').getAttribute('data-page'); NEWS.goTo(i); return a.getAttribute('data-open'); }""")
    page.wait_for_timeout(600)
    page.evaluate("(id) => document.querySelector(`#book .page-inner > .more-list a[data-open=\"${id}\"]`).click()", target)
    page.wait_for_selector("#reader:not([hidden]) .reader-body .item")
    got = page.evaluate("() => document.querySelector('#reader .reader-body .item').getAttribute('data-issue')")
    assert got == target and not errors, (got, target, errors)
    ctx.close()


def test_curated_topic_off_moves_list_to_briefs(browser, tmp_path):
    index = _b_site(tmp_path, _site())
    ctx, page, errors = open_page(browser, index, 1180, 820)
    info = page.evaluate("""() => { const ml = document.querySelector('#flow section[data-section=politics] > .more-list');
      return ml ? { topics: [...new Set([...ml.querySelectorAll('li')].map(li => li.getAttribute('data-topic')))],
                    ids: [...ml.querySelectorAll('a[data-open]')].map(a => a.getAttribute('data-open')) } : null; }""")
    assert info and info["ids"], info
    weights = {t: 0 for t in info["topics"]}
    page.evaluate("(w) => { localStorage.setItem('news.prefs2', JSON.stringify({v: 1, weights: w, keywords: null, updated: null})); NEWS_FB.reapply(); }", weights)
    page.wait_for_timeout(800)
    st = page.evaluate("() => NEWS.state()")
    left = page.evaluate("""(ids) => ids.filter(i => document.querySelector(`#flow .more-list a[data-open="${i}"]`))""", info["ids"])
    in_briefs = page.evaluate("""(ids) => ids.filter(i => document.querySelector(`#flow section[data-section=briefs] > article.item[data-issue="${i}"]`))""", info["ids"])
    m = page.evaluate(M, KEEP)
    assert not left and sorted(in_briefs) == sorted(info["ids"]), (left, in_briefs)
    assert not st["overflow"] and not m["listOnly"] and all(m["listLast"].values()), (st, m)
    assert not errors, errors
    ctx.close()


def test_curated_interest_promotion_before_list(browser, tmp_path):
    index = _b_site(tmp_path, _site())
    ctx, page, errors = open_page(browser, index, 1180, 820)
    topics = page.evaluate("() => [...new Set([...document.querySelectorAll('#flow section[data-section=briefs] > article.item')].map(a => a.getAttribute('data-topic')))]")
    page.evaluate("(w) => { localStorage.setItem('news.prefs2', JSON.stringify({v: 1, weights: w, keywords: null, updated: null})); NEWS_FB.reapply(); }",
                  {t: 3 for t in topics})
    page.wait_for_timeout(800)
    r = page.evaluate("""() => { const s = document.querySelector('#flow section[data-section=interest]'); if (!s) return null;
      const kids = [...s.children].filter(c => c.matches('article.item, .more-list'));
      return { up: s.querySelectorAll(':scope > article.item[data-moved=up]').length, last: !s.querySelector(':scope > .more-list') || kids[kids.length - 1].matches('.more-list'),
               head: !!s.querySelector(':scope > article.item.sec-head') }; }""")
    m = page.evaluate(M, KEEP)
    assert r and r["last"] and r["head"], r
    assert all(m["listLast"].values()) and not errors, (m, errors)
    ctx.close()
