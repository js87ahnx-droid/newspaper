"""S14b 매체 머리기사: 네이버 A1면·피드·홈페이지 읽기, 그날 기사와 맞추기."""
import asyncio
from datetime import date

import httpx
import numpy as np

from pipeline import headlines as H
from pipeline.collect import Article
from pipeline.render import headline_label
from pipeline.settings import Sources


def art(i, source, title, url=None):
    return Article(id=f"a{i}", url=url or f"https://{source.lower()}.test/news/{i}", source=source, country="KR", lean="중도",
                   media_type="종합지", weight=1.0, paywall=False, kind="rss", title=title, lead="", lang="ko",
                   published="2026-10-15T12:00:00+00:00", date_source="feed", sections=["top"],
                   first_seen="2026-10-15T12:00:00+00:00")


NAVER = ('<div><h3><span class="page_notation"><em>A1</em>면</span></h3> <ul class="newspaper_article_lst">'
         '<li><a href="x"><strong>주저앉은 코스피, 넉달새 3560P 날아갔다</strong></a></li>'
         '<li><a href="y"><strong>브런슨 &ldquo;전작권 전환 조건 변해&rdquo;</strong></a></li></ul>'
         '<h3><span class="page_notation"><em>A2</em>면</span></h3><ul class="newspaper_article_lst">'
         '<li><strong>2면 기사</strong></li></ul></div>')


def test_parse_naver_a1_only_front_page():
    assert H.parse_naver_a1(NAVER) == ["주저앉은 코스피, 넉달새 3560P 날아갔다", "브런슨 “전작권 전환 조건 변해”"]
    assert H.parse_naver_a1("<html>지면 없음</html>") == []
    # 한겨레처럼 면 이름이 '1'
    assert H.parse_naver_a1(NAVER.replace("<em>A1</em>", "<em>1</em>"))[0].startswith("주저앉은")


def test_parse_homepage_keeps_only_that_outlets_articles_in_order():
    arts = [art(1, "D", "부천 공장 화재 진압 중 소방관 순직", "https://www.d.test/news/1"),
            art(2, "D", "코스피 7% 넘게 급락 마감, 서킷브레이커 발동", "https://d.test/news/2")]
    html = ('<a href="/menu">정치</a><a href="https://ad.test/x">광고 클릭</a>'
            '<a href="/news/2?ref=main">코스피</a><a href="https://m.d.test/news/1/">순직</a><a href="/news/2">중복</a>')
    assert H.parse_homepage(html, "https://www.d.test/", arts) == [
        ("코스피 7% 넘게 급락 마감, 서킷브레이커 발동", "https://d.test/news/2"), ("부천 공장 화재 진압 중 소방관 순직", "https://www.d.test/news/1")]


def test_match_by_url_title_and_embedding_with_rejection():
    arts = [art(1, "동아일보", "주저앉은 코스피, 넉달새 3560P 날아갔다"),
            art(2, "동아일보", "[단독] 정부, 청해부대 작전범위 오만만으로 확대 검토"),
            art(3, "동아일보", "전자발찌 착용자 접근하면 경찰에 자동 경보 의무화"),
            art(4, "한겨레", "주저앉은 코스피, 넉달새 3560P 날아갔다")]
    heads = [H.Headline("동아일보", 1, "주저앉은 코스피, 넉달새 3560P 날아갔다", "naver_a1"),
             H.Headline("동아일보", 2, "청해부대 작전 오만만으로 확대", "naver_a1"),          # 표현만 다름 → 어휘로
             H.Headline("동아일보", 3, "경찰에 8번 신고했는데 또 막지 못한 죽음", "naver_a1"),  # 애매 → 임베딩 기준 미달이면 버림
             H.Headline("BBC", 1, "Oregon school shooting leaves three dead", "feed", url="https://bbc.test/1")]          # 그 매체 기사 없음
    vecs = np.eye(4)
    H.match(heads, arts, vecs, embed=lambda ts: np.array([[0.0, 0.0, 0.85, 0.0]] * len(ts)))
    assert (heads[0].article_id, heads[0].how) == ("a1", "title")   # 같은 제목인 다른 매체(a4)는 고르지 않음
    assert (heads[1].article_id, heads[1].how) == ("a2", "title")
    assert heads[2].article_id is None and heads[3].article_id is None
    h = H.Headline("동아일보", 3, "완전히 다른 표현으로 쓴 종이신문 1면 제목", "naver_a1")
    H.match([h], arts, vecs, embed=lambda ts: np.array([[0.0, 0.0, 0.95, 0.0]]))
    assert (h.article_id, h.how) == ("a3", "embed")


def test_fetch_falls_back_and_reports():
    srcs = Sources.model_validate({"sources": [
        {"name": "동아일보", "country": "KR", "lean": "보수", "type": "종합지", "weight": 1.0, "paywall": False, "enabled": True,
         "feeds": [{"section": "top", "url": "https://d.test/rss"}],
         "headline": [{"kind": "naver_a1", "press": "020"}, {"kind": "homepage", "url": "https://d.test/"}]},
        {"name": "BBC", "country": "UK", "lean": "통신·공영", "type": "방송", "weight": 1.0, "paywall": False, "enabled": True,
         "feeds": [{"section": "top", "url": "https://b.test/rss"}], "headline": [{"kind": "feed", "url": "https://b.test/top"}]},
        {"name": "AP", "country": "US", "lean": "통신·공영", "type": "통신", "weight": 1.0, "paywall": False, "enabled": True,
         "feeds": [{"section": "top", "url": "https://a.test/rss"}], "headline": [{"kind": "homepage", "url": "https://a.test/"}]},
    ]})
    rss = ('<?xml version="1.0"?><rss><channel><item><title>Top one</title><link>https://b.test/1</link></item>'
           '<item><title>Second</title><link>https://b.test/2</link></item></channel></rss>')

    def handler(req):
        if req.url.host == "media.naver.com":
            assert req.url.params["date"] == "20261017"
            return httpx.Response(200, text="<html>토요일: 지면 없음</html>")
        if req.url.host == "d.test":
            return httpx.Response(200, text='<a href="/news/1">x</a>')
        if req.url.host == "b.test":
            return httpx.Response(200, text=rss)
        return httpx.Response(403)

    arts = [art(1, "동아일보", "부천 공장 화재 진압 중 소방관 순직", "https://d.test/news/1")]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    heads, status = asyncio.run(H.fetch(srcs, date(2026, 10, 17), arts, client=client))
    assert [(h.source, h.rank, h.via) for h in heads] == [("동아일보", 1, "homepage"), ("BBC", 1, "feed"), ("BBC", 2, "feed")]
    assert status["동아일보"] == "homepage" and status["AP"].startswith("homepage 403")


def test_issue_headlines_and_label():
    heads = [{"source": "조선일보", "rank": 2, "via": "naver_a1", "article_id": "a1"},
             {"source": "조선일보", "rank": 1, "via": "naver_a1", "article_id": "a2"},
             {"source": "BBC", "rank": 1, "via": "feed", "article_id": "a3"},
             {"source": "동아일보", "rank": 1, "via": "homepage", "article_id": "zz"}]
    by = H.issue_headlines(heads, ["a1", "a2", "a3"])
    assert by == {"조선일보": [1, "naver_a1"], "BBC": [1, "feed"]}
    assert headline_label(by) == "1면 조선 / 헤드라인 BBC"
    assert headline_label({}) is None


def test_group_by_llm_and_embedding_fallback():
    arts = [art(1, "동아일보", "주저앉은 코스피"), art(2, "한겨레", "AI 거품론 코스피 폭락"),
            art(3, "경향신문", "청해부대 작전 확대"), art(4, "조선일보", "호르무즈 인근 청해부대")]
    def heads():
        return [H.Headline(a.source, 1, a.title, "naver_a1", article_id=a.id) for a in arts] + [
            H.Headline("BBC", 1, "unmatched", "feed")]
    hs = heads()
    assert H.group(hs, arts, None, ask=lambda p: {"groups": [[0, 1], [2, 3], ["x"], [9]]}) == "LLM"
    assert [h.group for h in hs] == [0, 0, 1, 1, None]
    # LLM 없으면 같은 언어 코사인 ≥ 0.90 끼리
    vecs = np.array([[1, 0, 0], [0.95, 0.31, 0], [0, 1, 0], [0, 0.6, 0.8]], dtype=float)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    hs = heads()
    assert H.group(hs, arts, vecs, ask=None) == "임베딩"
    assert hs[0].group is not None and hs[0].group == hs[1].group and hs[2].group is None and hs[3].group is None
    # LLM 이 실패하면 임베딩으로
    hs = heads()
    assert H.group(hs, arts, vecs, ask=lambda p: None) == "임베딩"


def test_group_credit_shared_across_issues():
    heads = [{"source": "동아일보", "rank": 1, "via": "naver_a1", "article_id": "a1", "group": 0},
             {"source": "한겨레", "rank": 2, "via": "naver_a1", "article_id": "a2", "group": 0},
             {"source": "경향신문", "rank": 1, "via": "naver_a1", "article_id": "a3", "group": None}]
    assert H.issue_headlines(heads, ["a1"]) == {"동아일보": [1, "naver_a1"], "한겨레": [2, "naver_a1"]}
    assert H.group_members(heads) == [{"a1", "a2"}]


def test_short_menu_titles_never_match():
    """메뉴·섹션 항목("Business")이 같은 주소·제목의 수집 항목과 맞지 않는다."""
    arts = [art(1, "CNN", "Business", "https://edition.cnn.com/business"),
            art(2, "CNN", "Why Trump decided to fire his press secretary", "https://edition.cnn.com/2026/10/17/politics/x")]
    html = '<a href="/business">Business</a><a href="/2026/10/17/politics/x">Why Trump decided</a>'
    assert H.parse_homepage(html, "https://edition.cnn.com/", arts) == [(arts[1].title, arts[1].url)]
    h = H.Headline("CNN", 1, "Business", "homepage", url="https://edition.cnn.com/business")
    H.match([h], arts)
    assert h.article_id is None


# ---- S47 신문 A2~A6면 (지면 비중) ----
from pathlib import Path  # noqa: E402

PAGES = Path(__file__).parent / "data" / "naver_1113"


def test_parse_naver_pages_on_saved_1113_pages():
    """저장된 11/13 네이버 신문 보기 7곳(면 번호·제목만): A1~A6 만, "1면"(한겨레)·"A1" 둘 다, B·E 섹션은 안 읽음. A1 은 기존과 같음."""
    for f in sorted(PAGES.glob("*.html")):
        html = f.read_text(encoding="utf-8")
        rows = H.parse_naver_pages(html)
        pages = {pg for pg, _, _ in rows}
        assert pages <= {f"A{n}" for n in range(1, 7)} and "A1" in pages and len(pages) >= 4, (f.name, pages)
        assert [t for pg, _, t in rows if pg == "A1"][: H.TOP_N] == H.parse_naver_a1(html), f.name
        a3 = [k for pg, k, _ in rows if pg == "A3"]
        assert a3 == list(range(1, len(a3) + 1))   # 면 안 순서
    joongang = H.parse_naver_pages((PAGES / "025.html").read_text(encoding="utf-8"))
    assert not any(t.startswith("성북·구로마저") for _, _, t in joongang)   # E1면(경제 섹션)은 안 읽음


def _page_heads():
    return [
        H.Headline("동아일보", 1, "AI 록스타 몰락하다… 젠슨 황, 불륜으로 엔비디아 CEO 사임", "naver_a1", article_id="a1", page="A1", group=0),
        H.Headline("한겨레", 1, "젠슨 황 결국 불명예 퇴진", "naver_a1", article_id="a2", page="A1", group=0),
        H.Headline("동아일보", 2, "베선트 “메가스피드 제재” 러트닉 “中과 무역전쟁 될것”… 백악관 충돌", "naver_page", article_id="a3", page="A4"),
        H.Headline("한겨레", 1, "미 정부 ‘경제 투톱’ 젠슨 황 스캔들 충돌", "naver_page", article_id="a3", page="A3"),
        H.Headline("한겨레", 2, "젠슨 황 퇴진 기로", "naver_page", article_id="a1", page="A3"),   # 한겨레는 같은 사건을 A1 에도 — 안 셈
    ]


def test_page_rows_stay_out_of_headline_paths():
    """naver_page 는 1면·머리기사 표시, 기사거리 묶음, 같은 사건 이웃 어디에도 안 들어간다 (S47 리뷰)."""
    heads = _page_heads()
    js = H.to_json(heads)
    by = H.issue_headlines(js, ["a3"])
    assert by == {}   # A4·A3 면만 있는 이슈는 1면·머리기사 표시 없음
    assert all("a3" not in m for m in H.group_members(js))
    calls = []
    H.group(heads, [art(1, "동아일보", "x" * 20)], None, ask=lambda p: calls.append(p) or {"groups": []})
    assert calls and "백악관 충돌" not in calls[0] and "퇴진 기로" not in calls[0]


def test_issue_pages_counts_each_paper_once_and_skips_its_a1():
    js = H.to_json(_page_heads())
    assert H.issue_pages(js, ["a3"]) == {"동아일보": "A4", "한겨레": "A3"}
    assert H.issue_pages(js, ["a1"], {"동아일보", "한겨레"}) == {}   # 그 신문이 A1 에 실은 이슈는 안 셈


def test_page_titles_fall_back_to_other_outlets():
    """같은 신문 기사가 수집에 없으면 다른 매체 같은 기사와 맞춘다 (자카드 0.5 이상). 비슷하지 않으면 안 맞춤."""
    arts = [art(1, "연합뉴스", "베선트 “메가스피드 제재” 러트닉 “中과 무역전쟁 될것”…백악관 충돌"),
            art(2, "연합뉴스", "국토장관 재초환 집값 안정 효과 있지만 재산권 침해도")]
    hs = [H.Headline("중앙일보", 1, "베선트 “메가스피드 제재” 러트닉 “中과 무역전쟁 될것”… 백악관 충돌", "naver_page", page="A3"),
          H.Headline("중앙일보", 2, "엔비디아 플랜B 있나 하루아침에 안 무너져 엇갈린 진단", "naver_page", page="A4")]
    H.match(hs, arts)
    assert (hs[0].article_id, hs[0].how) == ("a1", "title-cross")
    assert hs[1].article_id is None
    # 1면(naver_a1)은 지금처럼 같은 매체 기사하고만
    a1 = [H.Headline("중앙일보", 1, hs[0].title, "naver_a1", page="A1")]
    H.match(a1, arts)
    assert a1[0].article_id is None


def test_fetch_adds_page_rows_after_a1():
    srcs = Sources.model_validate({"sources": [
        {"name": "중앙일보", "country": "KR", "lean": "보수", "type": "종합지", "weight": 1.0, "paywall": False, "enabled": True,
         "feeds": [{"section": "top", "url": "https://j.test/rss"}], "headline": [{"kind": "naver_a1", "press": "025"}]}]})
    html = (PAGES / "025.html").read_text(encoding="utf-8")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=html)))
    heads, status = asyncio.run(H.fetch(srcs, date(2026, 11, 13), [], client=client))
    a1 = [h for h in heads if h.via == "naver_a1"]
    pg = [h for h in heads if h.via == "naver_page"]
    assert [h.page for h in a1] == ["A1"] * len(a1) and len(a1) <= H.TOP_N and status["중앙일보"] == "naver_a1"
    assert pg and {h.page for h in pg} <= {"A2", "A3", "A4", "A5", "A6"}


def test_page_rows_without_korean_articles_do_not_crash():
    """S47 리뷰: 맞출 국내 기사가 하나도 없으면 임베딩 단계에서 건너뛴다 (전에는 빈 목록에서 order[0] 오류)."""
    hs = [H.Headline("중앙일보", 1, "엔비디아 플랜B 있나 하루아침에 안 무너져 엇갈린 진단", "naver_page", page="A4")]
    eng = Article(id="e1", url="https://x.test/1", source="AP", country="US", lean="통신·공영", media_type="통신", weight=1.0,
                  paywall=False, kind="rss", title="Nvidia CEO resigns after board review", lead="", lang="en",
                  published="2026-11-12T12:00:00+00:00", date_source="feed", sections=["top"], first_seen="2026-11-12T12:00:00+00:00")
    H.match(hs, [eng], np.ones((1, 3)) / np.sqrt(3), embed=lambda ts: np.ones((len(ts), 3)) / np.sqrt(3))
    assert hs[0].article_id is None
