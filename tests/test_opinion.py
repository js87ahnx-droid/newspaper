"""S9b 논평·사설."""
import asyncio
from datetime import date, datetime, timezone

import httpx
import pytest

from pipeline.collect import Article, collect, load_store
from pipeline.opinion import MAX_COLUMNS, organize
from pipeline.prepare import prepare, prepare_opinions
from pipeline.settings import Sources, load_config
from pipeline.textutil import detect_opinion

CFG = load_config()
UTC = timezone.utc


@pytest.mark.parametrize(
    "title, url, section, expect",
    [
        ("[사설] 여의도 정치 올인", "https://www.chosun.com/opinion/editorial/2026/1", "", "editorial"),
        ("국무회의 생중계 축소 [사설]", "https://news.google.com/rss/articles/x", "", "editorial"),
        ("The Guardian view on Stormont", "https://www.theguardian.com/commentisfree/2026/x", "", "editorial"),
        ("[朝鮮칼럼] 생각하는 군대", "https://www.chosun.com/opinion/chosun_column/1", "", "column"),
        ("[기고]우리는 왜", "https://www.khan.co.kr/article/1", "", "column"),
        ("[김경의 별잇기 예술여행]여행자처럼", "https://www.khan.co.kr/article/2", "", "column"),
        ("[횡설수설/윤완준]국무회의 생중계", "https://www.donga.com/news/Opinion/article/all/1", "", "column"),
        ("Trump's Diesel Deal", "https://www.nytimes.com/2026/10/15/opinion/x.html", "", "column"),
        ("아무 제목", "https://x.test/1", "opinion", "column"),
        ("[단독] 김지용 임명", "https://www.yna.co.kr/view/1", "", None),
        ("[속보] 李대통령", "https://x.test/2", "", None),
        ("[MK포토] 김강률", "https://x.test/3", "", None),
        ("[책과 삶]9개 문화권", "https://www.khan.co.kr/article/3", "", None),
        ("[오늘의 날씨] 10월 16일", "https://x.test/4", "", None),          # "○○의 …" 이지만 필자 연재 아님
        ("[내일의 국감](16일)", "https://x.test/5", "", None),
        ("[뉴스광장 2부 헤드라인]", "https://x.test/6", "", None),        # '광장' 이 들어가도 칼럼 아님
        ("[장혜수의 뉴스터치] 압록강은 흐르는데", "https://x.test/7", "", "column"),
    ],
)
def test_detect_opinion(title, url, section, expect):
    assert detect_opinion(title, url, section) == expect


def art(i, source="조선일보", lean="보수", title="t", lead="", published="2026-10-15T12:00:00+00:00",
        opinion=None, sections=("top",), lang="ko", country="KR", weight=1.0):
    return Article(
        id=f"a{i}", url=f"https://x.test/{i}", source=source, country=country, lean=lean, media_type="종합지",
        weight=weight, paywall=False, kind="rss", title=title, lead=lead, lang=lang, published=published,
        date_source="feed", sections=list(sections), first_seen=published, opinion=opinion,
    )


def sources(*names):
    return Sources.model_validate({"sources": [
        {"name": n, "country": "KR", "lean": "보수", "type": "종합지", "weight": 1.0, "paywall": False,
         "enabled": True, "feeds": [{"section": "top", "url": "https://x.test/rss"}]} for n in names]})


def test_opinions_kept_out_of_news_and_use_wider_window():
    store = {
        "a1": art(1, title="[사설] 밤 사설", published="2026-10-15T13:00:00+00:00", opinion="editorial"),  # 22:00 KST
        "a2": art(2, title="낮 칼럼", published="2026-10-15T03:00:00+00:00", sections=("opinion",)),  # 의견 피드, 12:00 KST 전날
        "a3": art(3, title="이틀 전 칼럼", published="2026-10-14T03:00:00+00:00", sections=("opinion",)),  # 24시간 밖
        "a4": art(4, title="뉴스 기사", published="2026-10-15T13:00:00+00:00"),
        "a5": art(5, title="[기고]판별값 없이 저장된 옛 기사", published="2026-10-15T13:00:00+00:00"),  # 다시 판별
    }
    news, rep = prepare(store, date(2026, 10, 16), CFG, sources("조선일보"))
    assert [a.title for a in news] == ["뉴스 기사"]
    assert rep["opinion_separated"] == 2  # 뉴스 시간창 안의 의견 기사 (a1, a5)
    ops = prepare_opinions(store, date(2026, 10, 16), CFG, sources("조선일보"))
    assert {a.title for a in ops} == {"[사설] 밤 사설", "낮 칼럼", "[기고]판별값 없이 저장된 옛 기사"}
    assert ops[0].opinion == "editorial"  # 사설 먼저


def test_google_news_title_must_filter(tmp_path):
    srcs = Sources.model_validate({"sources": [{
        "name": "중앙일보", "country": "KR", "lean": "보수", "type": "종합지", "weight": 1.0, "paywall": False, "enabled": True,
        "feeds": [{"section": "opinion", "url": "https://g.test/rss", "kind": "google_news", "title_must": "[사설]"}]}]})
    body = ('<?xml version="1.0"?><rss><channel><title>t</title>'
            '<item><title>[사설] 경찰청장 공석 - 중앙일보</title><link>https://g.test/1</link><pubDate>Thu, 15 Oct 2026 22:00:00 +0900</pubDate></item>'
            '<item><title>일반 기사 - 중앙일보</title><link>https://g.test/2</link><pubDate>Thu, 15 Oct 2026 22:00:00 +0900</pubDate></item>'
            '</channel></rss>').encode()

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))) as c:
            await collect(srcs, tmp_path / "s.jsonl", now=datetime(2026, 10, 15, 20, 0, tzinfo=UTC), client=c)

    asyncio.run(go())
    store = load_store(tmp_path / "s.jsonl")
    assert [(a.title, a.opinion) for a in store.values()] == [("[사설] 경찰청장 공석", "editorial")]


def edition_with(issue_titles):
    items = [{"issue_id": f"i{k}", "title": t, "articles": [{"title": t, "lead": t, "lang": "ko"}]} for k, t in enumerate(issue_titles)]
    return {"sections": {"front": items}}


def test_editorial_compare_by_lean_and_column_cap():
    ed = edition_with(["국민연금 주식 비중 증시 폭락 안전판", "전작권 전환 한미 조건 재검토"])
    ops = [
        art(1, "조선일보", "보수", "[사설] 폭락장에서 안전판 잃은 국민연금", "국민연금 주식 비중 증시 폭락", opinion="editorial"),
        art(2, "한겨레", "진보", "[사설] 국민연금 주식 비중, 증시 폭락 탓만 할 일인가", "국민연금 안전판 논란", opinion="editorial"),
        art(3, "동아일보", "보수", "[사설] 전작권 시간표 진지한 재검토를", "전작권 전환 한미 조건", opinion="editorial"),
        art(4, "매일경제", "경제지", "[사설] 서울 집값 88주 상승", "부동산 정책", opinion="editorial"),
    ] + [art(10 + k, f"매체{k % 4}", "중도", f"칼럼 {k}", "", opinion="column") for k in range(20)]
    out = organize(ops, ed)
    # 같은 이슈를 보수·진보가 사설로 → 비교 블록
    assert len(out["compare"]) == 1
    cmp = out["compare"][0]
    assert cmp["issue_id"] == "i0" and [g["lean"] for g in cmp["groups"]] == ["보수", "진보"]
    # 비교에 쓴 사설은 목록에서 빠지고, 나머지는 성향 순
    assert [e["source"] for e in out["editorials"]] == ["동아일보", "매일경제"]
    assert out["editorials"][0]["issue_id"] == "i1"            # 전작권 사설은 이슈와 연결
    assert out["editorials"][1]["issue_id"] is None            # 집값 사설은 지면 이슈 없음
    # 칼럼: 최대 10편, 한 매체 2편까지
    assert len(out["columns"]) <= MAX_COLUMNS
    per = {}
    for c in out["columns"]:
        per[c["source"]] = per.get(c["source"], 0) + 1
    assert max(per.values()) <= 2


def test_rendered_opinion_section_has_no_body(tmp_path):
    from pipeline.render import render
    from pipeline.settings import load_interests, load_sources
    from tests.test_render_browser import ItemParser, make_site  # noqa: F401
    from pipeline.textutil import LEAD_MAX

    index = make_site(tmp_path)
    import json
    # make_site 결과 지면에 논평·사설을 붙여 다시 렌더
    ed_json = {"edition": "2026-10-16", "sections": {"front": []}, "compare": [], "stats": {}}
    ed_json["opinion"] = organize([
        art(1, "조선일보", "보수", "[사설] 테스트 사설", "리드 " * 200, opinion="editorial"),
        art(2, "한겨레", "진보", "칼럼 제목", "리드", opinion="column"),
    ], {"sections": {"front": []}})
    out = render(ed_json, load_config(), load_interests(), load_sources(), tmp_path / "site2")
    html = out.read_text(encoding="utf-8")
    assert 'data-section="opinion"' in html and "오늘의 사설" in html and "주요 칼럼·논평" in html
    p = ItemParser()
    p.feed(html)
    assert not p.too_long


def test_link_needs_two_rare_shared_words():
    """'생중계' 한 낱말만 겹치는 칼럼은 이슈에 잇지 않는다 (10/16호 실제 오연결 사례)."""
    from pipeline.opinion import link_to_issues

    items = [{"issue_id": "t", "title": "트럼프 미군기지 난사범 총살형 생중계되지 않을 것",
              "articles": [{"title": "트럼프 미군기지 난사범 총살형 생중계되지 않을 것", "lead": "", "lang": "ko"}]},
             {"issue_id": "k", "title": "김지용 중수청장 임명안 재가",
              "articles": [{"title": "김지용 중수청장 임명안 재가", "lead": "중대범죄수사청 초대 청장", "lang": "ko"}]}]
    ops = [art(1, "동아일보", "보수", "[횡설수설]국무회의 생중계", "정부는 국무회의를 생중계하고 있다", opinion="column"),
           art(2, "경향신문", "진보", "[사설]김지용 초대 중수청장, 독립성 확보를", "중대범죄수사청 초대 청장 김지용", opinion="editorial")]
    links = link_to_issues(ops, items, common_by_lang={"ko": set()})
    assert "a1" not in links
    assert links["a2"][0] == "k"


def test_editorials_grouped_by_topic_across_outlets():
    from pipeline.opinion import group_editorials

    eds = [art(1, "조선일보", "보수", "[사설] 폭락장에서 안전판 잃은 국민연금", "국민연금 주식 비중", opinion="editorial"),
           art(2, "한국경제", "경제지", "[사설] 사지도 팔지도 못하는 국민연금", "국민연금 운용원칙", opinion="editorial"),
           art(3, "조선일보", "보수", "[사설] 국민연금 또 다른 사설", "국민연금 주식", opinion="editorial"),
           art(4, "한겨레", "진보", "[사설] 신천지 집단가입 규명", "신천지 정당 가입", opinion="editorial")]
    groups = group_editorials(eds)
    assert len(groups) == 1 and {a.source for a in groups[0]} >= {"조선일보", "한국경제"}
