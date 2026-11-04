"""S37c 중국은 지금 쪽 — 실제 브라우저로.

- AI 결과가 있으면 국제 뒤에 "중국은 지금" 쪽(두 덩어리), 없으면 쪽 없음
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


@pytest.mark.parametrize("w,h", [(390, 844), (1180, 820), (820, 1180)])
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
                ev: document.querySelectorAll('#book .cn-ev .orig-btn[data-art]').length}; }""")
    ctx.close()
    assert not errors, errors
    assert m["parts"] == 2 and 1 <= m["cn"] <= 2, m
    assert m["after"] == 1, m                    # 국제 바로 뒤
    assert m["clipped"] == 0 and m["overflow"] == 0 and m["sw"] <= 1 and m["brief"] == 0, m
    assert m["ev"] == 2                           # 근거 기사 → 원문 창


def test_china_title_breaks_between_words(browser, tmp_path):  # noqa: F811
    """제목이 "'환율 안정'으 / 로"처럼 낱말 중간에서 끊기지 않는다 (2026-11-04)."""
    def mutate(out):
        add_china(out)
        out["china"]["title"] = "위안화 상승 억제가 아니라 '환율 안정'으로 — 인민일보의 외화지준율 인상 프레임"
    index = make_site(tmp_path, mutate=mutate)
    ctx, page, errors = open_page(browser, index, 390, 844)
    m = page.evaluate("""() => {
        const el = document.querySelector('#book .cn-title'), t = el.firstChild, s = t.data, r = document.createRange();
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
