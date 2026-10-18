"""S22c 분석·해설(매체가 쓴 분석), S22d 지정 칼럼."""
from datetime import date, datetime, timezone

import pytest

from pipeline.collect import Article
from pipeline.opinion import ANALYSIS_PER_SOURCE, organize_analysis, recent_picks
from pipeline.prepare import _side_kind, prepare, prepare_opinions, prepare_side
from pipeline.settings import load_config, load_sources
from pipeline.textutil import detect_analysis
from tests.test_render_browser import browser, make_site  # noqa: F401

CFG, SRC = load_config(), load_sources()


@pytest.mark.parametrize("title,url,sec,want", [
    ("[뉴스 분석] 금리 동결의 배경", "https://www.yna.co.kr/x", "", True),
    ("반도체 수출 왜 줄었나 [분석+]", "https://www.hankyung.com/x", "", True),
    ("Takeaways from the first debate", "https://www.nytimes.com/x", "", True),
    ("Who pays for the war?", "https://www.economist.com/briefing/2026/10/15/x", "", True),
    ("新华述评｜全球经济", "https://www.news.cn/x", "", True),
    ("Macron : décryptage – analyse", "https://www.lemonde.fr/x", "", True),
    ("Anything from a feed", "https://x.test/a", "analysis", True),
    ("Match of the Day analysis", "https://www.bbc.co.uk/x", "analysis", False),   # 잡음 표시는 전용 피드여도 뺌
    ("Why mortgage rates are rising", "https://www.cnn.com/x", "", False),           # 질문형 제목은 잡지 않음
    ("코스피 2% 상승 마감", "https://www.yna.co.kr/x", "", False),
])
def test_detect_analysis(title, url, sec, want):
    assert detect_analysis(title, url, sec) is want


def _art(i, source, title, url, sections, published="2026-10-17T10:00:00+00:00", lang="en"):
    return Article(id=f"a{i}", source=source, country="UK", lean="중도", media_type="종합지", weight=1.0, paywall=False,
                   kind="rss", title=title, lead="", url=url, lang=lang, published=published, date_source="feed",
                   sections=sections, first_seen=published)


def test_side_articles_are_not_news_or_opinion():
    """분석·지정 칼럼은 뉴스·논평 목록에 섞이지 않고 따로 모인다. 지정 칼럼은 시간창 밖(지난주)도 남는다."""
    store = {a.id: a for a in [
        _art(1, "Guardian", "Analysis: why the Fed waits", "https://www.theguardian.com/a1", ["top"]),
        _art(2, "Guardian", "Fed holds rates", "https://www.theguardian.com/a2", ["top"]),
        _art(3, "조선비즈", "[김지수의 인터스텔라] 인터뷰", "https://biz.chosun.com/topics/kjs_interstellar/x", ["column_pick"],
             published="2026-10-10T00:00:00+00:00", lang="ko"),
        _art(4, "Guardian", "The Guardian view on rates", "https://www.theguardian.com/commentisfree/a4", ["opinion"]),
    ]}
    news, _ = prepare(store, date(2026, 10, 18), CFG, SRC)
    ops = prepare_opinions(store, date(2026, 10, 18), CFG, SRC)
    an = prepare_side(store, date(2026, 10, 18), CFG, SRC, "analysis")
    picks = prepare_side(store, date(2026, 10, 18), CFG, SRC, "pick")
    assert [a.id for a in news] == ["a2"] and [a.id for a in ops] == ["a4"]
    assert [a.id for a in an] == ["a1"] and [a.id for a in picks] == ["a3"]
    assert _side_kind(store["a3"]) == "pick"


def test_organize_analysis_mixes_sources():
    arts = [_art(i, "Financial Times", f"Analysis: t{i}", f"https://www.ft.com/{i}", ["analysis"]) for i in range(5)]
    arts += [_art(10 + i, "Guardian", f"Analysis: g{i}", f"https://www.theguardian.com/{i}", ["analysis"]) for i in range(1)]
    out = organize_analysis(arts)
    from collections import Counter
    assert max(Counter(a["source"] for a in out).values()) <= ANALYSIS_PER_SOURCE and len({a["source"] for a in out}) == 2
    assert recent_picks([{"u": 1}, {"u": 2}, {"u": 3}]) == [{"u": 1}, {"u": 2}]


def test_analysis_page_and_pick_box_render(browser, tmp_path):  # noqa: F811
    def mut(out):
        out["analysis"] = [{"id": f"x{i}", "source": "Financial Times", "lean": "경제지", "country": "UK", "lang": "en",
                            "title": f"Why the Fed is stuck {i}", "lead": "lead text here", "url": f"https://www.ft.com/content/{i}",
                            "paywall": True, "published": "2026-10-17T10:00:00+00:00", "ko_title": f"연준은 왜 갇혔나 {i}",
                            "ko_summary": "연준의 고민을 분석한다."} for i in range(3)]
        out["picks"] = [{"id": "p1", "source": "조선비즈", "lean": "경제지", "country": "KR", "lang": "ko",
                         "title": "[김지수의 인터스텔라] 테스트 인터뷰", "lead": "", "paywall": False,
                         "url": "https://biz.chosun.com/topics/kjs_interstellar/2026/10/17/X/", "published": "2026-10-16T23:21:00+00:00"}]
    index = make_site(tmp_path, mutate=mut)
    ctx = browser.new_context(viewport={"width": 1180, "height": 820}, reduced_motion="reduce")
    ctx.add_init_script("try{localStorage.setItem('news.survey', '2099-W01');}catch(e){}")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(index.as_uri())
    page.wait_for_function("window.NEWS && window.NEWS.state().pages > 0")
    m = page.evaluate("""() => { const ps = [...document.querySelectorAll('#book .page')];
      const an = ps.filter(p => p.classList.contains('sec-analysis'));
      const op = ps.find(p => p.classList.contains('sec-opinion'));
      return {an: an.length, items: an.flatMap(p => [...p.querySelectorAll('article.item.an')]).length,
              title: an.length ? an[0].querySelector('.sec-title').textContent : '',
              ko: an.length ? an[0].querySelector('.item.an .hl a').textContent : '',
              art: an.length ? an[0].querySelector('.item.an .hl a').hasAttribute('data-art') : false,
              pickFirst: op ? op.querySelector('article.item').classList.contains('oppick') : false,
              pick: op ? (op.querySelector('.oppick .pick-t a') || {}).textContent : '', state: NEWS.state()}; }""")
    ctx.close()
    assert not errors and m["state"]["overflow"] == []
    assert m["an"] >= 1 and m["items"] == 3 and m["title"].startswith("분석·해설") and m["ko"].startswith("연준은") and m["art"]
    assert m["pickFirst"] and "인터스텔라" in m["pick"]


def test_detect_analysis_skips_breaking_roundups_and_sports():
    """S22c 평가: 'What we know about ~'(사건 사실 정리)·스포츠 해설은 분석면에 넣지 않는다."""
    assert not detect_analysis("What we know about the 16-year-old who opened fire", "https://www.cnn.com/x")
    assert not detect_analysis("What to know: NCAA's 5-in-5 eligibility rule", "https://apnews.com/x")
    assert detect_analysis("What to Know About the Violent Protests in Albania", "https://www.nytimes.com/x")
    assert not detect_analysis("Analysis | A unified front won't save Commanders", "https://www.washingtonpost.com/sports/2026/10/17/x/")
