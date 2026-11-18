"""S37c 중국은 지금 쪽 — 실제 브라우저로.

- AI 결과가 있으면 국제 뒤에 "중국은 지금" 한 쪽(S54 ② — 지면엔 앞부분 + 들어가는 만큼의 다른 나라 매체, 제목 → 창에 전부), 없으면 쪽 없음
- 휴대폰(390)·패드(1180)에서 넘치거나 잘리지 않고, 가로로 밀리지 않음
- 근거 기사 단추는 원문 창으로
"""
import pytest

from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)


def add_china(out):
    it = out["sections"]["international"][0]
    out["china"] = {
        "issue_id": it["issue_id"], "title": "대미 반도체 통제에 \"자립\"을 앞세운 인민일보 — 피해보다 기술 굴기를 강조",
        "lead": "인민일보는 사흘째 1면과 논평에서 미국의 새 수출 통제를 패권적 괴롭힘으로 규정하면서 지면 대부분을 국산 장비·소재의 성과에 할애했다. "
                "피해 규모나 기업 어려움은 다루지 않았다.",
        "emphasis": ["미국 조치의 부당성 — 다자 무역 질서 훼손", "자립 성과 — 국산 노광장비·메모리 생산량", "당 중앙의 지도", "신질 생산력"],
        "omitted": ["수출 감소", "기업 실적 악화", "인력 유출"],
        "keywords": ["自立自强", "新质生产力", "霸凌"],
        "compare": [{"source": "Wall Street Journal", "country": "US", "lean": "보수", "focus": "중국 업체 재고 바닥, 우회 수입 단속"},
                    {"source": "Financial Times", "country": "UK", "lean": "중도", "focus": "네덜란드·일본 장비사 매출 영향"},
                    {"source": "Nikkei Asia", "country": "JP", "lean": "경제지", "focus": "일본 소재 기업의 중국 의존도"},
                    {"source": "연합뉴스", "country": "KR", "lean": "통신·공영", "focus": "삼성·SK 중국 공장 예외 연장 여부"}],
        "agenda": ["장정 승리 90주년", "신질 생산력", "고품질 발전"],
        "evidence": [{"source": "인민일보", "title": "坚定不移推进科技自立自强", "url": "https://paper.people.com.cn/a.html", "lang": "zh"},
                     {"source": "Wall Street Journal", "title": "China's chip stockpile runs low as curbs tighten", "url": "https://wsj.test/b", "lang": "en"}],
    }


@pytest.mark.parametrize("w,h", [(390, 844), (1180, 820), (820, 1180), (1366, 1024)])
def test_china_page_fits(browser, tmp_path, w, h):  # noqa: F811
    index = make_site(tmp_path, mutate=add_china)
    ctx, page, errors = open_page(browser, index, w, h)
    m = page.evaluate("""() => {
        const pages = [...document.querySelectorAll('#book .page')];
        const cn = pages.filter(p => p.querySelector('.cn-view'));
        const order = [...new Set(pages.map(p => ([...p.classList].find(c => c.startsWith('sec-')) || '').slice(4)).filter(Boolean))];
        return {cn: cn.length, parts: document.querySelectorAll('#book .cn-view').length,
                after: order.indexOf('china') - order.indexOf('international'),
                clipped: NEWS.state().clipped, overflow: NEWS.state().overflow.length,
                sw: document.scrollingElement.scrollWidth - innerWidth,
                brief: document.querySelectorAll('#book .item.brief[data-section="china"]').length,
                note: [...document.querySelectorAll('#book .cn-view .cn-note')].filter(x => x.offsetHeight > 0).length,
                rows: [...document.querySelectorAll('#book .cn-view .cn-row')].filter(x => x.offsetHeight > 0).length,
                hiddenRows: [...document.querySelectorAll('#book .cn-view .cn-row')].filter(x => x.offsetHeight === 0).length,
                used: (() => { const p = [...document.querySelectorAll('#book .page')].find(p => p.querySelector('.cn-view'));
                  const inn = p.querySelector('.page-inner'), r = inn.getBoundingClientRect(); let b = r.top;
                  [...inn.children].forEach(c => { const q = c.getBoundingClientRect(); if (q.height > 0) b = Math.max(b, q.bottom); });
                  return (b - r.top) / r.height; })()}; }""")
    ctx.close()
    assert not errors, errors
    assert m["parts"] == 1 and m["cn"] == 1, m   # S54 ②: 한 쪽
    assert m["after"] == 1, m                     # 국제 바로 뒤
    assert m["clipped"] == 0 and m["overflow"] == 0 and m["sw"] <= 1 and m["brief"] == 0, m
    assert m["note"] == 1, m                      # "AI 해석" 안내는 늘 보임
    assert m["hiddenRows"] == 0 or m["used"] >= 0.85, m   # 다른 매체 줄이 남아 있으면 아래 여백 < 15%


def _short_economy(out):
    """경제 면이 한 쪽으로 줄어 중국은 지금이 짝수 쪽에서 시작하게 되는 날."""
    add_china(out)
    out["sections"]["economy"] = out["sections"]["economy"][:1]


CHINA_PAGES = """() => {
    const pages = [...document.querySelectorAll('#book .page')];
    const cn = pages.filter(p => p.querySelector('.cn-view'));
    const order = [...new Set(pages.map(p => ([...p.classList].find(c => c.startsWith('sec-')) || '').slice(4)).filter(Boolean))];
    return {at: cn.map(p => pages.indexOf(p)), left: cn.map(p => p.classList.contains('pg-left')), order,
            total: pages.length, folio: cn.map(p => p.querySelector('.folio').textContent)}; }"""


def test_china_one_page_on_spread(browser, tmp_path):  # noqa: F811
    """S54 ②: 한 쪽이라 펼침 보기에서도 옮기지 않고 국제 바로 뒤 (chinaOnSpread 없앰)."""
    index = make_site(tmp_path, mutate=_short_economy)
    ctx, page, errors = open_page(browser, index, 1180, 820)
    m = page.evaluate(CHINA_PAGES)
    ctx.close()
    assert not errors, errors
    assert len(m["at"]) == 1 and m["order"].index("china") - m["order"].index("international") == 1, m
    assert m["total"] % 2 == 0, m


def test_china_title_opens_window_with_everything(browser, tmp_path):  # noqa: F811
    index = make_site(tmp_path, mutate=add_china)
    ctx, page, errors = open_page(browser, index, 390, 844)
    page.evaluate("() => { const a = document.querySelector('#book .cn-title a[data-detail]'); a.scrollIntoView(); a.click(); }")
    page.wait_for_selector("#reader:not([hidden]) .cn-view")
    r = page.evaluate("""() => { const v = document.querySelector('#reader .cn-view'), vis = s => [...v.querySelectorAll(s)].filter(x => x.offsetHeight > 0).length;
        return { rows: vis('.cn-row'), agenda: vis('.cn-agenda'), ev: vis('.cn-ev .orig-btn'), words: vis('.cn-words'), emph: vis('.cn-emph li'), ft: !!v.querySelector('.ft') }; }""")
    assert r == {"rows": 4, "agenda": 1, "ev": 2, "words": 1, "emph": 4, "ft": False}, r
    page.keyboard.press("Escape")
    page.evaluate("() => NEWS.goTo(+document.querySelector('#book .cn-title a').closest('.page').getAttribute('data-page'))")
    page.wait_for_timeout(700)
    page.evaluate("() => document.querySelector('#book .cn-title a').focus()")
    page.keyboard.press("Enter")
    page.wait_for_selector("#reader:not([hidden]) .cn-view")
    assert not errors, errors
    ctx.close()


def test_china_keeps_place_on_portrait(browser, tmp_path):  # noqa: F811
    """한 쪽씩 보는 세로 화면은 좌우 묶음이 없으니 국제 바로 뒤 그대로."""
    index = make_site(tmp_path, mutate=_short_economy)
    ctx, page, errors = open_page(browser, index, 390, 844)
    m = page.evaluate(CHINA_PAGES)
    ctx.close()
    assert not errors, errors
    assert m["order"].index("china") - m["order"].index("international") == 1, m


def test_china_title_breaks_between_words(browser, tmp_path):  # noqa: F811
    """제목이 "'환율 안정'으 / 로"처럼 낱말 중간에서 끊기지 않는다 (2026-11-04)."""
    def mutate(out):
        add_china(out)
        out["china"]["title"] = "위안화 상승 억제가 아니라 '환율 안정'으로 — 인민일보의 외화지준율 인상 프레임"
    index = make_site(tmp_path, mutate=mutate)
    ctx, page, errors = open_page(browser, index, 390, 844)
    m = page.evaluate("""() => {
        const el = document.querySelector('#book .cn-title a'), t = el.firstChild, s = t.data, r = document.createRange();   // S54: 제목은 링크 안
        const top = i => { r.setStart(t, i); r.setEnd(t, i + 1); return r.getBoundingClientRect().top; };
        const bad = []; let lines = 1, last = top(0);
        for (let i = 1; i < s.length; i++) {
          if (s[i] === ' ') continue;
          const y = top(i);
          if (y > last + 2) { lines++; if (s[i - 1] !== ' ') bad.push(s.slice(i - 3, i + 2)); last = y; }
        }
        return {bad, lines}; }""")
    ctx.close()
    assert not errors, errors
    assert m["lines"] >= 2 and m["bad"] == [], m


def test_no_china_no_page(browser, tmp_path):  # noqa: F811
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, 1180, 820)
    n = page.evaluate("document.querySelectorAll('[data-section=\"china\"]').length")
    ctx.close()
    assert n == 0 and not errors


def test_china_screenshot(browser, tmp_path):  # noqa: F811
    """눈으로 보는 캡처: build/s37-china-{phone,pad}.png"""
    from pathlib import Path
    index = make_site(tmp_path, mutate=add_china)
    out = Path(__file__).resolve().parent.parent / "build"
    for name, (w, h) in {"phone": (390, 844), "pad": (1180, 820)}.items():
        ctx, page, _ = open_page(browser, index, w, h)
        i = page.evaluate("[...document.querySelectorAll('#book .page')].findIndex(p => p.querySelector('.cn-view'))")
        page.evaluate(f"NEWS.goTo({i})")
        page.wait_for_timeout(900)
        page.screenshot(path=str(out / f"s37-china-{name}.png"))
        ctx.close()
    assert (out / "s37-china-pad.png").stat().st_size > 0
