"""S31b 경제 기사 심화 해설: 대상 고르기·묶음·응답 반영·skip·거르기·캐시·아는 개념 (가짜 runner)."""
import json
from datetime import date

from pipeline.llm import ECON_PROMPT, Budget, econ_dive, econ_targets, enrich
from pipeline.settings import Llm, load_interests

BODY = ("한국은행 금융통화위원회는 23일 기준금리를 연 3.0%로 동결했다. 두 차례 연속 인상한 뒤 대외 불확실성이 커져 "
        "효과를 지켜보겠다는 판단이다. 이창용 총재는 기자간담회에서 추가 인상 가능성을 열어 뒀다. ") * 3
DIVE = {"concepts": ["금리 인상 사이클의 일시 정지", "한·미 금리차와 환율"],
        "theory": "통화정책은 시차를 두고 효과를 낸다. 연속 인상 뒤에는 효과를 확인하려 쉬어 가는 경우가 많다.",
        "practice": "실제로는 동결 자체보다 다음 금리 경로를 시장이 어떻게 읽느냐가 시장금리와 환율에 더 크게 작용한다.",
        "analysis": ["원인: 누적 긴축 효과 점검.", "파급: 대출금리 상승세 둔화."],
        "watch": [{"what": "소비자물가", "why": "동결의 전제가 이어지는지 본다."}, {"what": "", "why": "빈 지표는 버림"}]}


def item(iid, topic="economy", final=0.5, reserve=False, url=None):
    url = url or f"https://a.test/{iid}"
    return {"issue_id": iid, "title": f"기사 {iid}", "lead": "리드", "topic": topic, "reserve": reserve, "scores": {"final": final},
            "articles": [{"id": "a" + iid, "url": url, "source": "연합뉴스", "lean": "중도", "country": "KR", "lang": "ko",
                          "title": f"기사 {iid}", "lead": "리드", "published": "2026-10-23T01:00:00+00:00"}]}


def cfg(**kw):
    return Llm(enabled=True, model="haiku", max_calls_per_day=20, timeout_sec=10, analysis_issues=0, econ_batch=2, **kw)


def runner(out_by_id, calls):
    def run(prompt):
        calls.append(prompt)
        return json.dumps({"result": json.dumps({"issues": out_by_id}, ensure_ascii=False)})
    return run


def guarded_with(run, calls_kw):
    def guarded(prompt, **kw):
        calls_kw.append(kw)
        out = json.loads(run(prompt))["result"]
        return json.loads(out), "ok"
    return guarded


def test_targets_economy_fields_by_score_without_reserves():
    items = [item("1", "economy", 0.3), item("2", "politics", 0.9), item("3", "semis_ai", 0.8), item("4", "industry", 0.5),
             item("5", "economy", 0.95, reserve=True), item("6", "economy", 0.1)]
    assert [it["issue_id"] for it in econ_targets(items, 3)] == ["3", "4", "1"]
    assert [it["issue_id"] for it in econ_targets(items, 10)] == ["3", "4", "1", "6"]


def test_dive_batches_cleans_and_skips():
    items = [item("1", final=0.9), item("2", final=0.8), item("3", final=0.7)]
    prompts, kws = [], []
    run = runner({"1": DIVE, "2": {"skip": True}, "3": {**DIVE, "practice": ""}}, prompts)
    cache = {}
    got, st = econ_dive(items, {}, cfg(), cache, guarded_with(run, kws), ["밸류에이션"], {"1": {"summary": "AI 요약 문장"}})
    assert len(prompts) == 2 and all(kw["model"] == "opus" and kw["timeout"] == 600 for kw in kws)   # 2건 + 1건
    assert list(got) == ["1"]
    assert got["1"]["watch"] == [{"what": "소비자물가", "why": "동결의 전제가 이어지는지 본다."}]   # 빈 지표는 버림
    assert st["ok"] == 1 and st["skip"] == 1 and st["rejected"] == {"3": "이론·실제 비어 있음"}
    assert cache["econ"]["2"] == {"skip": True} and "3" not in cache["econ"]
    assert "독자가 이미 안다고 한 개념: 밸류에이션" in prompts[0] and "AI 요약 문장" in prompts[0]
    # 같은 호 다시: 캐시된 것(1·2)은 묻지 않고, 버린 3만 다시
    prompts2 = []
    econ_dive(items, {}, cfg(), cache, guarded_with(runner({}, prompts2), []), [], None)
    assert len(prompts2) == 1 and '"id": "3"' in prompts2[0] and "(없음)" in prompts2[0]


def test_dive_rejects_copied_body_and_bad_answers():
    items = [item("1", url="https://a.test/body"), item("2")]
    copied = {**DIVE, "theory": "기사에 따르면 " + BODY[10:90]}
    prompts = []
    got, st = econ_dive(items, {"https://a.test/body": BODY}, cfg(), {}, guarded_with(runner({"1": copied, "2": "문자열"}, prompts), []), [])
    assert got == {} and st["rejected"] == {"1": "본문 그대로 옮김", "2": "응답 없음"}
    assert "한국은행 금융통화위원회" in prompts[0]   # 본문은 프롬프트에만


def test_enrich_attaches_econ_and_never_saves_body(tmp_path):
    calls = []
    eco, pol = item("1", url="https://a.test/body"), item("2", topic="politics")
    ed = {"sections": {"economy": [eco], "politics": [pol]}, "compare": [], "stats": {}}
    budget = Budget(tmp_path / "u.json", date(2026, 10, 23), 20)
    out = enrich(ed, cfg(), load_interests().foreign_display, tmp_path / "llm.json", budget,
                 runner=runner({"1": DIVE}, calls), bodies={"https://a.test/body": BODY}, known=["금리"])
    it = out["sections"]["economy"][0]
    assert it["llm"]["econ"]["concepts"] == DIVE["concepts"] and "econ" not in out["sections"]["politics"][0].get("llm", {})
    assert out["stats"]["llm"]["econ"]["ok"] == 1 and out["stats"]["llm"]["status"]["econ"] == "1/1 ok"
    saved = (tmp_path / "llm.json").read_text(encoding="utf-8")
    assert "한국은행 금융통화위원회" not in saved and json.loads(saved)["econ"]["1"]["theory"] == DIVE["theory"]
    assert any("독자가 이미 안다고 한 개념: 금리" in c for c in calls)


def test_prompt_rules():
    for rule in ("지어내지 말 것", "권유 금지", "단정하지 말 것", "skip", "theory", "practice", "watch"):
        assert rule in ECON_PROMPT
