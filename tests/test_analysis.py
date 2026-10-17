"""S14 본문 기반 이슈 분석: 본문 받기, 요약 검사, 본문 베끼기 거부, 저장 안 함."""
import asyncio
import json
from datetime import date

import httpx

from pipeline import bodies as B
from pipeline.llm import Budget, check_summary, enrich, new_facts, title_overlap
from pipeline.settings import Llm, load_interests

BODY = ("서울시는 16일 지하철 9호선 연장 구간을 다음 달 1일 개통한다고 밝혔다. 새 구간은 중앙보훈병원역에서 고덕역까지 "
        "4.1㎞로 정거장 4곳이 생긴다. 시는 출퇴근 시간 배차 간격을 3분대로 줄이고 급행열차도 함께 운행할 계획이다. ") * 3
TITLE = "지하철 9호선 연장 구간 개통"


def item(iid="i1", url="https://a.test/1", title=TITLE):
    return {"issue_id": iid, "title": title, "lead": "리드", "timeline": [
        {"date": "2026-10-15", "title": "9호선 연장 시운전", "summary": "시운전 시작"}],
        "articles": [{"id": "a1", "url": url, "source": "연합뉴스", "lean": "중도", "country": "KR", "lang": "ko",
                      "title": title, "lead": "리드", "published": "2026-10-16T01:00:00+00:00"},
                     {"id": "a2", "url": "https://b.test/2", "source": "한겨레", "lean": "진보", "country": "KR", "lang": "ko",
                      "title": "9호선 4단계 다음달 개통", "lead": "리드2", "published": "2026-10-16T02:00:00+00:00"}]}


GOOD = {"headline": "9호선 강동 연장 내달 개통", "summary": (
    "서울시가 9호선 중앙보훈병원~고덕 4.1㎞ 구간을 11월 1일 연다. 정거장 네 곳이 새로 생기며 출퇴근 배차를 3분대로 "
    "줄이고 급행도 다닌다. 강동권 주민의 도심 이동 시간이 짧아질 전망이다."),
    "background": "지난달 시운전을 시작했다.", "points": ["혼잡도"], "brief": "9호선 연장, 내달 1일 개통",
    "stances": [{"source": "연합뉴스", "view": "개통 일정과 운행 계획을 전함"}, {"source": "한겨레", "view": "주민 교통 편의에 초점"}]}


def runner_with(out_by_id, calls):
    def run(prompt):
        calls.append(prompt)
        return json.dumps({"result": json.dumps({"issues": out_by_id}, ensure_ascii=False)})
    return run


def cfg(**kw):
    return Llm(enabled=True, model="haiku", max_calls_per_day=10, timeout_sec=10, analysis_batch=2, **kw)


def test_summary_checks():
    assert check_summary(GOOD["summary"], [TITLE]) is None
    assert check_summary("지하철 9호선 연장 구간 개통 지하철 9호선 연장 구간 개통 지하철 9호선 연장 구간 개통", [TITLE]) == "제목 되풀이"
    assert check_summary("짧다", [TITLE]) == "짧음"
    assert title_overlap(GOOD["summary"], TITLE) < 0.6 and new_facts(GOOD["summary"], TITLE) >= 3


def test_copied_span_detects_verbatim_body():
    copied = "기사에 따르면 " + BODY[20:90] + " 라고 한다."
    assert B.copied_span(copied, [BODY])
    assert B.copied_span(GOOD["summary"], [BODY]) is None


def test_analysis_attached_and_body_never_saved(tmp_path):
    calls = []
    ed = {"sections": {"front": [item()]}, "compare": [], "stats": {}}
    budget = Budget(tmp_path / "u.json", date(2026, 10, 16), 10)
    out = enrich(ed, cfg(), load_interests().foreign_display, tmp_path / "llm.json", budget,
                 runner=runner_with({"i1": GOOD}, calls), bodies={"https://a.test/1": BODY})
    an = out["sections"]["front"][0]["llm"]["analysis"]
    assert an["headline"] == GOOD["headline"] and len(an["stances"]) == 2
    # 프롬프트에는 본문, 지난 경과가 들어가고
    assert "중앙보훈병원역" in calls[0] and "시운전 시작" in calls[0] and "(본문 없음)" in calls[0]
    # 저장된 캐시에는 LLM 글만 (본문 문장 없음)
    saved = (tmp_path / "llm.json").read_text(encoding="utf-8")
    assert "중앙보훈병원역에서 고덕역까지" not in saved and GOOD["brief"] in saved
    assert out["stats"]["llm"]["analysis"]["articles_with_body"] == 1


def test_analysis_rejects_repeat_and_copy(tmp_path):
    repeat = dict(GOOD, summary=f"{TITLE}. {TITLE}. {TITLE}.")
    copied = dict(GOOD, summary="서울시 발표 내용이다. " + BODY[:120])
    ed = {"sections": {"front": [item("i1"), item("i2", url="https://a.test/2")]}, "compare": [], "stats": {}}
    out = enrich(ed, cfg(), load_interests().foreign_display, tmp_path / "llm.json",
                 Budget(tmp_path / "u.json", date(2026, 10, 16), 10),
                 runner=runner_with({"i1": repeat, "i2": copied}, []), bodies={"https://a.test/2": BODY})
    rej = out["stats"]["llm"]["analysis"]["rejected"]
    assert rej == {"i1": "제목 되풀이", "i2": "본문 그대로 옮김"}
    assert all("analysis" not in it.get("llm", {}) for it in out["sections"]["front"])


def test_analysis_limited_to_top_issues_and_batched(tmp_path):
    calls = []
    items = [item(f"i{n}", url=f"https://a.test/{n}") for n in range(5)]
    ed = {"sections": {"front": items[:2], "briefs": items[2:]}, "compare": [], "stats": {}}
    enrich(ed, cfg(analysis_issues=3), load_interests().foreign_display, tmp_path / "llm.json",
           Budget(tmp_path / "u.json", date(2026, 10, 16), 10), runner=runner_with({}, calls))
    analysis_calls = [c for c in calls if "headline" in c]
    assert len(analysis_calls) == 2  # 상위 3개를 2개씩 → 2회
    assert '"i3"' not in "".join(analysis_calls) and '"i4"' not in "".join(analysis_calls)


def test_fetch_bodies_statuses(monkeypatch):
    html = "<html><body><article><h1>t</h1>" + "".join(f"<p>{BODY}</p>" for _ in range(2)) + "</article></body></html>"

    def handler(req):
        if req.url.host == "ok.test":
            return httpx.Response(200, text=html)
        if req.url.host == "short.test":
            return httpx.Response(200, text="<html><body><p>짧은 안내</p></body></html>")
        return httpx.Response(403)

    async def fake_decode(urls, timeout):
        return {u: ("https://ok.test/g" if "good" in u else None) for u in urls}

    monkeypatch.setattr(B, "_decode_google", fake_decode)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    res = asyncio.run(B.fetch_bodies([
        "https://ok.test/1", "https://short.test/1", "https://block.test/1",
        "https://news.google.com/rss/articles/good", "https://news.google.com/rss/articles/bad"], client=client))
    assert res["https://ok.test/1"].status == "ok" and "중앙보훈병원역" in res["https://ok.test/1"].text
    assert len(res["https://ok.test/1"].text) <= B.MAX_CHARS
    assert res["https://short.test/1"].status in ("짧음", "추출 실패")
    assert res["https://block.test/1"].status == "http 403"
    assert res["https://news.google.com/rss/articles/good"].url == "https://ok.test/g"
    assert res["https://news.google.com/rss/articles/bad"].status == "google 풀기 실패"


def test_structured_data_fallbacks():
    fusion = ('<script>Fusion.globalContent={"content_elements":[{"type":"text","content":"<b>첫</b> 문단"},'
              '{"type":"image"},{"type":"text","content":"둘째 문단"}]};Fusion.x=1;</script>')
    assert B._from_fusion(fusion) == "첫 문단\n둘째 문단"
    ld = '<script type="application/ld+json">{"@type":"NewsArticle","articleBody":"본문 &amp; 내용"}</script>'
    assert B._from_ldjson(ld) == "본문 & 내용"


def test_history_gets_llm_brief(tmp_path):
    from pipeline.__main__ import _history_summaries

    h = tmp_path / "2026-10-16.json"
    h.write_text(json.dumps({"edition": "2026-10-16", "issues": [
        {"id": "i1", "timeline": [{"date": "2026-10-16", "title": "t", "summary": None}]},
        {"id": "i2", "timeline": [{"date": "2026-10-16", "title": "u", "summary": None}]}]}), encoding="utf-8")
    ed = {"sections": {"front": [{"issue_id": "i1", "llm": {"analysis": GOOD}}, {"issue_id": "i2"}]}}
    _history_summaries(h, ed)
    data = json.loads(h.read_text(encoding="utf-8"))
    assert data["issues"][0]["timeline"][-1]["summary"] == GOOD["brief"]
    assert data["issues"][1]["timeline"][-1]["summary"] is None


def test_llm_analysis_merges_same_event_across_languages():
    from pipeline.llm import merge_duplicates

    def it(iid, src, an):
        return {"issue_id": iid, "articles": [{"id": iid, "source": src, "country": "KR" if src == "연합" else "US"}],
                "coverage": {"sources": 1}, "llm": {"analysis": an}}

    same = dict(GOOD, headline="신압록강대교 12년 만에 개통")
    other = dict(GOOD, headline="TSMC 6분기 연속 최대 순익", summary="TSMC는 3분기 순이익이 68.7% 늘었다. AI 칩 수요가 이끌었고 내년 투자도 늘린다.")
    ed = {"sections": {"front": [it("e1", "AP", same)], "politics": [it("k1", "연합", dict(same)), it("t1", "Reuters", other)]}}
    assert merge_duplicates(ed) == [("e1", "k1")]
    assert [x["issue_id"] for x in ed["sections"]["politics"]] == ["t1"]
    host = ed["sections"]["front"][0]
    assert host["merged"] == ["k1"] and host["coverage"]["sources"] == 2 and host["coverage"]["countries"] == 2
