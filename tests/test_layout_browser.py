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
    return sum(s.pages for s in load_config().sections)   # S17e: 단신이 한 줄이 되어 휴대폰도 같은 쪽수


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
    """정해진 쪽에 다 못 들어간 기사는 남는 쪽의 '더 읽을 기사'(S18)나 단신으로 내려가고, 단신으로 간 것은
    단신 분야 묶음마다 맨 앞(점수 순) — S19c. 더 읽을 기사에 간 것이 단신에 간 것보다 점수가 높다."""
    index = make_site(tmp_path)
    ctx, page, _ = open_page(browser, index, 1024, 768)
    st = page.evaluate(STATE)
    rows = page.evaluate("""() => [...document.querySelectorAll('#book .page.sec-briefs article.item')]
        .map(a => [a.dataset.topic, a.classList.contains('demoted'), +(a.dataset.final2 || a.dataset.final)])""")
    more = page.evaluate("""() => [...document.querySelectorAll('#book .page.sec-more article.item')]
        .filter(a => a.dataset.reserve !== '1').map(a => +(a.dataset.final2 || a.dataset.final))""")
    ctx.close()
    assert st["demoted"] == sum(1 for r in rows if r[1])
    assert st["demoted"] + len(more) > 0
    assert more == sorted(more, reverse=True)
    if more and st["demoted"]:
        assert min(more) >= max(r[2] for r in rows if r[1])
    for t in {r[0] for r in rows}:
        grp = [r for r in rows if r[0] == t]
        flags = [r[1] for r in grp]
        assert flags == sorted(flags, reverse=True)          # 내려온 기사가 묶음 앞
        dem = [r[2] for r in grp if r[1]]
        assert dem == sorted(dem, reverse=True)


@pytest.mark.parametrize("w,h", [(1180, 820), (820, 1180), (390, 844)])
def test_briefs_are_one_line(browser, tmp_path, w, h):  # noqa: F811
    """S17e: 단신은 기사마다 가로 한 줄 (줄바꿈 없음), 한 단."""
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, w, h)
    m = page.evaluate("""() => {
      const ps = [...document.querySelectorAll('#book .page.sec-briefs')];
      ps.forEach(p => p.style.display = '');
      const rows = ps.flatMap(p => [...p.querySelectorAll('.item.brief')]);
      const lh = rows.map(r => { const t = r.querySelector('.hl'); return [r.getBoundingClientRect().height, t ? t.getBoundingClientRect().height : 0]; });
      return {n: rows.length, maxH: Math.max(...lh.map(x => x[0])), maxT: Math.max(...lh.map(x => x[1])),
              grid: document.querySelectorAll('.brief-grid').length, end: document.querySelectorAll('#book .page.endpage').length}; }""")
    ctx.close()
    assert not errors
    assert m["n"] >= 5 and m["grid"] == 0
    assert m["maxH"] <= 36 and m["maxT"] <= 30, m   # 한 줄 높이


@pytest.mark.parametrize("w,h", [(1180, 820), (390, 844)])
def test_briefs_grouped_by_topic(browser, tmp_path, w, h):  # noqa: F811
    """S19c: 단신은 분야 소제목 아래로. 한 분야는 한 묶음(쪽이 바뀌면 "(이어서)"), 소제목은 늘 첫 단신과 함께, 넘친 쪽 0."""
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, w, h)
    m = page.evaluate("""() => {
      const ps = [...document.querySelectorAll('#book .page.sec-briefs')];
      ps.forEach(p => p.style.display = '');
      const rows = ps.flatMap(p => [...p.querySelectorAll('.item.brief')].map(a => a.dataset.topic));
      const heads = ps.flatMap(p => [...p.querySelectorAll('.brief-topic')].map(h => h.textContent));
      const lone = [...document.querySelectorAll('#book .brief-group')].filter(g => !g.querySelector('.item.brief')).length;
      const firsts = ps.map(p => { const a = p.querySelector('.item.brief'); return a ? !!a.closest('.brief-group') : true; });
      return {rows, heads, lone, firsts, topics: EDITION.briefTopics, names: EDITION.topics}; }""")
    st = page.evaluate(STATE)
    ctx.close()
    assert not errors and st["overflow"] == []
    runs = [t for i, t in enumerate(m["rows"]) if i == 0 or m["rows"][i - 1] != t]
    assert len(runs) == len(set(runs)) >= 2                                  # 분야마다 한 번
    rank = {t: i for i, t in enumerate(m["topics"])}
    assert [rank.get(t, 99) for t in runs] == sorted(rank.get(t, 99) for t in runs)   # 분야 중요도 순
    fresh = [h for h in m["heads"] if not h.endswith("(이어서)")]
    assert fresh == [m["names"].get(t, "기타") for t in runs]
    assert m["lone"] == 0 and all(m["firsts"])                              # 소제목만 남은 곳 없음, 쪽 첫 단신엔 소제목


def _thin_day(out):
    """얇은 날 흉내: 관심면을 비워 쪽을 남긴다 (그 기사는 지면에서 뺌). """
    out["sections"]["interest"] = []


@pytest.mark.parametrize("w,h", [(1180, 820), (390, 844)])
def test_spare_pages_get_more_articles_not_blank(browser, tmp_path, w, h):  # noqa: F811
    """S21c: 남는 쪽은 예비 기사를 일반 기사 모양으로 '더 읽을 기사' 면에 — 끝 빈 쪽 없음, 단신은 정해진 쪽 안."""
    index = make_site(tmp_path, mutate=_thin_day, n_issues=200)   # 예비 60건이 다 차도록
    ctx, page, errors = open_page(browser, index, w, h)
    m = page.evaluate("""() => { const ps = [...document.querySelectorAll('#book .page')];
      const more = ps.filter(p => p.classList.contains('sec-more'));
      return {end: ps.filter(p => p.classList.contains('endpage')).length, more: more.length,
              briefs: ps.filter(p => p.classList.contains('sec-briefs')).length,
              full: more.flatMap(p => [...p.querySelectorAll('article.item')]).every(a => !a.classList.contains('brief')),
              res: more.flatMap(p => [...p.querySelectorAll('article.item')]).map(a => a.dataset.reserve === '1'),
              title: more.length ? more[0].querySelector('.sec-title').textContent : ''}; }""")
    st = page.evaluate(STATE)
    ctx.close()
    assert not errors and st["overflow"] == []
    assert m["end"] == 0 and m["more"] >= 1 and m["full"] and m["title"].startswith("더 읽을 기사"), m
    assert m["briefs"] <= next(s.pages for s in load_config().sections if s.id == "briefs")
    assert m["res"] == sorted(m["res"]) and any(m["res"]), m["res"]   # 내려온 기사(예비 아님)가 예비 기사보다 앞


def _thin_day_crowded_front(out):
    """얇은 날 + 1면이 넘치는 날: 관심면을 비워 쪽을 남기고, 1면 기사를 늘려 정해진 쪽에 다 못 들어가게."""
    _thin_day(out)
    out["sections"]["front"] = out["sections"]["front"] + out["sections"]["politics"][:6]
    out["sections"]["politics"] = out["sections"]["politics"][6:]


def test_demoted_front_items_go_to_more_before_reserves(browser, tmp_path):  # noqa: F811
    """S18: 1면에서 넘친 기사는 쪽이 남으면 단신이 아니라 '더 읽을 기사'에 일반 기사 꼴로, 예비 기사보다 앞에.
    (10/18호: 1면 다섯째 기사가 23쪽 단신에, 점수 낮은 예비 기사는 18~20쪽에 일반 기사 꼴로 실렸다)"""
    index = make_site(tmp_path, mutate=_thin_day_crowded_front, n_issues=200)
    ctx, page, errors = open_page(browser, index, 1180, 820)
    m = page.evaluate("""() => { const ps = [...document.querySelectorAll('#book .page')];
      const more = ps.filter(p => p.classList.contains('sec-more')).flatMap(p => [...p.querySelectorAll('article.item')]);
      const briefs = ps.filter(p => p.classList.contains('sec-briefs')).flatMap(p => [...p.querySelectorAll('article.item')]);
      return {more: more.map(a => a.dataset.section), briefsFront: briefs.filter(a => a.dataset.section === 'front').length}; }""")
    ctx.close()
    assert not errors
    k = m["more"].count("front")
    assert k >= 1 and m["more"][:k] == ["front"] * k, m      # 1면에서 넘친 기사가 더 읽을 기사 맨 앞
    assert m["briefsFront"] == 0, m


def _many_columns(out):
    col = {"issue_id": "", "url": "https://www.donga.com/news/Opinion/article/all/20261017/1", "kind": "column",
           "lean": "보수", "source": "동아일보", "title": "칼럼 제목이 꽤 긴 편입니다 [필자의 연재 이름]", "lang": "ko"}
    out["opinion"] = {"compare": [], "editorials": [], "columns": [dict(col, url=col["url"] + str(i)) for i in range(10)]}
    out["picks"] = [{"source": "조선비즈", "url": "https://biz.chosun.com/x", "title": "[김지수의 인터스텔라] 지정 칼럼",
                     "lang": "ko", "published": "2026-10-17T00:00:00+00:00"}]


def test_column_list_splits_across_pages(browser, tmp_path):  # noqa: F811
    """S18: 칼럼 목록은 5편씩 끊는다 — 10편이 한 덩어리라 통째로 다음 쪽으로 넘어가 논평면 첫 쪽이 비던 것 (10/18호 24쪽)."""
    index = make_site(tmp_path, mutate=_many_columns)
    ctx, page, errors = open_page(browser, index, 1180, 820)
    m = page.evaluate("""() => { const ps = [...document.querySelectorAll('#book .page.sec-opinion')];
      return {chunks: document.querySelectorAll('#flow [data-issue^="op-col"]').length,
              first: ps.length ? ps[0].querySelectorAll('.oplist li').length : -1,
              total: ps.reduce((n, p) => n + p.querySelectorAll('.oplist li').length, 0)}; }""")
    st = page.evaluate(STATE)
    ctx.close()
    assert not errors and st["overflow"] == []
    assert m["chunks"] == 2 and m["total"] == 10 and m["first"] >= 5, m


def test_brief_click_shows_summary_not_just_title(browser, tmp_path):  # noqa: F811
    """S22a: 단신 제목을 누르면 자세히 창에 리드(요약)까지 — 전에는 지면 원본도 한 줄 꼴이라 제목만 보였다."""
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, 1180, 820)
    r = page.evaluate("""() => {
      const b = [...document.querySelectorAll('#book .page.sec-briefs article.item.brief')]
        .find(a => { const f = document.querySelector('#flow [data-issue="' + a.dataset.issue + '"] .lead'); return f && f.textContent.trim(); });
      if (!b) return null;
      b.closest('.page').style.display = ''; const a = b.querySelector('.hl a'); a.scrollIntoView(); a.click();
      const body = document.querySelector('#reader .reader-body');
      return {open: !document.getElementById('reader').hidden, lead: (body.querySelector('.lead') || {}).textContent || '',
              oneLine: b.getBoundingClientRect().height}; }""")
    ctx.close()
    assert r, "요약이 있는 단신이 없음"
    assert r["open"] and len(r["lead"].strip()) > 10 and r["oneLine"] <= 36 and not errors
