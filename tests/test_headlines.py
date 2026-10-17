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
    assert headline_label(by) == "1면 조선 / 머리 BBC"
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
