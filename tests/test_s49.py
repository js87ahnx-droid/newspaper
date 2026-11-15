"""S49 기사 구성 다듬기 (2026-11-15 사용자 요청) — 데이터·고르기 시험. 화면은 test_s49_browser.

기준 (project-plan.md S49b·S49c)
- 한국어 제목·요약·부제: 표시 규칙, 부제 버림 규칙, 키 캐시(칸·분석 유무·제목), 우선순위, 관련 기사는 제목만
- 잘린 리드: 완결 판정과 끊기(40% 규칙)
"""
import json
import re

from pipeline.llm import KOREAN_BATCH, korean_pass, korean_targets
from pipeline.render import _display, deck_of
from pipeline.settings import load_interests
from pipeline.textutil import lead_complete, trim_lead

DISP = load_interests().foreign_display


def _it(iid, lang, title, lead="리드다.", **kw):
    return {"issue_id": iid, "title": title, "lead": lead,
            "articles": [{"id": iid, "source": "S", "country": "KR" if lang == "ko" else "US", "lang": lang, "title": title}], **kw}


# ---------- 잘린 리드 ----------
def test_lead_complete_and_trim():
    for s in ["그는 말했다.", 'He said "no."', "会談した。", "정말?", "(끝났다.)"]:
        assert lead_complete(s), s
    for s in ["시즌 7승째를 거뒀다. …", "계획···", "밝혔...", "트럼프 대통령이 앨", "The minister said"]:
        assert not lead_complete(s), s
    assert trim_lead("첫 문장이다. 둘째 문장도 끝났다. 셋째는 중간에서 끊") == "첫 문장이다. 둘째 문장도 끝났다. …"
    assert trim_lead("시즌 7승째를 거뒀다. …") == "시즌 7승째를 거뒀다. …"
    assert trim_lead("트럼프 대통령이 앨") == "트럼프 대통령이 앨…"                       # 완결 문장 없음 → "…"만
    assert trim_lead("짧다. 그리고 이 문장은 아주 길게 이어지면서 중간에서 끊긴다 왜냐하면 피드가") .endswith("피드가…")   # 40% 미만
    assert trim_lead("首脳は会談した。その後声明を発表し、記者会見を開く予定だっ").endswith("予定だっ…")
    assert trim_lead("完了した。次も完了した。最後は途中で") == "完了した。次も完了した。 …"
    assert trim_lead("끝난 문장.") == "끝난 문장."


# ---------- 표시 ----------
def test_display_uses_korean_title_and_summary_each_when_present():
    en = _it("e", "en", "Pope has surgery", "The pope had")
    v = _display(en, DISP)
    assert (v["title"], v["orig_title"], v["lead"], v["lead_note"]) == ("Pope has surgery", None, "The pope had…", None)   # 없으면 원문(잘린 리드는 끊기)
    en["llm"] = {"ko_title": "교황 수술"}
    v = _display(en, DISP)
    assert (v["title"], v["orig_title"], v["lead_note"]) == ("교황 수술", "Pope has surgery", "AI 번역 제목")
    en["llm"] = {"ko_summary": "교황이 수술을 받았다."}
    v = _display(en, DISP)
    assert (v["title"], v["orig_title"], v["lead"], v["lead_note"]) == ("Pope has surgery", None, "교황이 수술을 받았다.", "AI 요약")
    en["llm"] = {"ko_title": "교황 수술", "ko_summary": "교황이 수술을 받았다.", "deck": "회복에 2주 걸려"}
    v = _display(en, DISP)
    assert (v["title"], v["orig_title"], v["lead"], v["deck"]) == ("교황 수술", "Pope has surgery", "교황이 수술을 받았다.", "회복에 2주 걸려")
    ko = _it("k", "ko", "국내 기사", "트럼프 대통령이 앨", llm={"ko_summary": "트럼프 대통령이 회담에서 거론하지 않을 전망이다."})
    assert _display(ko, DISP)["lead"].endswith("전망이다.") and _display(ko, DISP)["title"] == "국내 기사"


def test_deck_rules():
    assert deck_of({"deck": "주가 이틀간 14% 하락"}, "젠슨 황 사임") == "주가 이틀간 14% 하락"
    assert deck_of({"deck": "가" * 41}, "제목") is None                 # 40자 넘음
    assert deck_of({"deck": "젠슨 황 사임!"}, "젠슨 황, 사임") is None    # 제목과 같음
    assert deck_of({}, "제목") is None
    an = _it("a", "ko", "원제목", llm={"analysis": {"headline": "정리 제목", "summary": "정리.", "brief": "b"}, "deck": "부제 한 줄"})
    assert _display(an, DISP)["deck"] == "부제 한 줄"


# ---------- 한국어 패스 ----------
def _edition():
    return {"sections": {
        "front": [_it("f1", "en", "Front story", "Lead.", related=[_it("r1", "ja", "関連記事"), _it("r2", "ko", "관련 기사")])],
        "international": [_it("i1", "ja", "国際記事", "リード。"), _it("i2", "ko", "국내 잘린 리드", "그는 말했"),
                          _it("i3", "ko", "국내 완결", "끝났다."),
                          _it("i4", "en", "Analyzed", "x", llm={"analysis": {"headline": "분석", "summary": "분석 요약."}})],
        "briefs": [_it("b1", "en", "Brief", "Brief lead."), _it("b2", "en", "Reserve", "R.", reserve=True), _it("b3", "ko", "국내 단신", "잘")],
    }, "compare": []}


def test_korean_targets_fields_and_priority():
    t = [(it["issue_id"], f) for it, f in korean_targets(_edition(), DISP)]
    assert t == [("f1", ["title", "summary", "deck"]),
                 ("i1", ["title", "summary", "deck"]), ("i2", ["summary", "deck"]), ("i3", ["deck"]), ("i4", ["deck"]),
                 ("r1", ["title"]),                                      # 관련 기사는 제목만 (한국어 관련 기사는 없음)
                 ("b1", ["title", "summary"]), ("b2", ["title", "summary"])]   # 단신 → 예비, 부제 없음. 국내 단신 잘린 리드는 요약 안 받음


def _runner(log, table=None):
    def guarded(prompt, **kw):
        log.append(prompt)
        ids = re.findall(r'"id": "([^"]+)"', prompt)
        need = {i: json.loads(m) for i, m in re.findall(r'"id": "([^"]+)".*?"필요": (\[[^\]]*\])', prompt, re.S)}
        return {"items": {k: {f: f"{k.split('|')[0]}-{f}" for f in need.get(k, ["title", "summary", "deck"])} for k in ids}}, "ok"
    return guarded


def test_korean_pass_attaches_and_caches_by_title_fields_and_analysis():
    ed, cache, log = _edition(), {}, []
    st = korean_pass(ed, DISP, cache, _runner(log))
    assert st.startswith("ok") and len(log) == 1
    f1 = ed["sections"]["front"][0]
    assert f1["llm"] == {"ko_title": "f1-title", "ko_summary": "f1-summary", "deck": "f1-deck"}
    assert f1["related"][0]["llm"] == {"ko_title": "r1-title"} and "llm" not in f1["related"][1]
    assert "llm" not in ed["sections"]["briefs"][2]                      # 국내 단신은 손대지 않음
    # 같은 입력 다시: 호출 없음
    ed2 = _edition()
    assert korean_pass(ed2, DISP, cache, _runner(log)) == "캐시" and len(log) == 1
    assert ed2["sections"]["front"][0]["llm"]["deck"] == "f1-deck"
    # 단신이던 기사가 뉴스 면으로 올라오면 부제만 더 받음, 대표 제목이 바뀐 기사는 다시, 분석이 생긴 기사는 부제 다시
    ed3 = _edition()
    b1 = ed3["sections"]["briefs"].pop(0)
    ed3["sections"]["international"].append(b1)
    ed3["sections"]["international"][0]["title"] = "国際記事 更新"
    ed3["sections"]["international"][2]["llm"] = {"analysis": {"headline": "생김", "summary": "생긴 분석."}}
    korean_pass(ed3, DISP, cache, _runner(log))
    sent = log[-1]
    assert len(log) == 2 and sent.count('"id"') == 3
    assert re.search(r'"id": "b1\|[^"]*",[^}]*"필요": \[\s*"deck"\s*\]', sent, re.S)
    assert "国際記事 更新" in sent and '"리드": "생긴 분석."' in sent


def test_korean_pass_cap_drops_lowest_priority():
    ed = {"sections": {"international": [_it(f"n{i}", "en", f"News {i}", "L.") for i in range(KOREAN_BATCH * 8)],
                       "briefs": [_it("z", "en", "Reserve", "R.", reserve=True)]}, "compare": []}
    log = []
    korean_pass(ed, DISP, {}, _runner(log))
    assert len(log) == 8 and not any("Reserve" in p for p in log)
    assert "llm" not in ed["sections"]["briefs"][0]



# ---------- S49c 종합면 각도별 ----------
from pipeline.llm import _clean_plan, plan_jonghap  # noqa: E402
from pipeline.render import jonghap, jonghap_hosts  # noqa: E402
from tests.test_jonghap import ROW, _a  # noqa: E402


def _plan(lead_id, groups):
    return {"lead": lead_id, "groups": [{"host": h, "band": b, "angles": {k: {"angle": ang, "dup": d is not None, "dup_of": d}
                                                                           for k, ang, d in rows}} for h, b, rows in groups]}


def _secs(main, second_angles=None):
    lead = {**_a("L", "젠슨 황 사임", "동아일보"), "angles": main, "view": {"title": "젠슨 황 사임"}}
    front = [{**_a("S", "충청 메가프로젝트 착공", "한겨레"), "angles": second_angles or [], "view": {"title": "메가프로젝트"}}]
    return [{"id": "front", "items": front, "lead": lead}, {"id": "politics", "items": []}]


def test_planned_jonghap_distinct_angles_dups_and_second_group():
    main = [_a(k, f"기사 {k}", "같은매체") for k in "abcdefg"]   # 매체 겹침 허용
    sec = [_a(k, f"둘째 {k}", "M") for k in "xyz"]
    plan = _plan("L", [("L", "젠슨 황 사임 후폭풍", [("a", "경위", None), ("b", "시장 반응", "L"), ("c", "시장 반응", None),
                                                  ("d", "시장 반응", None), ("e", "후임", "f"), ("f", "후임", "e"), ("g", "전망", None)]),
                       ("S", "충청 메가프로젝트", [("x", "현장", "S"), ("y", "쟁점", None), ("z", "현장", None)])])
    secs = _secs(main, sec)
    jonghap(secs, "종합", ROW, plan, secs[0]["items"][0])
    jh = secs[1]
    got = [(r["issue_id"], r["jh_angle"], r["jh_group"]) for r in jh["items"]]
    # b 는 메인과 같은 내용, d 는 c 와 같은 각도, f 는 e 를 가리킴(e 가 먼저 남음) -> a c e g / x 는 둘째 이슈와 같은 내용 -> y z
    assert got == [("a", None, 0), ("c", "시장 반응", 0), ("e", "후임", 0), ("g", "전망", 0), ("y", "쟁점", 1), ("z", "현장", 1)]
    assert jh["theme"] == "젠슨 황 사임 후폭풍" and jh["theme_named"] and jh["items"][4]["jh_band"] == "충청 메가프로젝트"
    assert "jh_band" not in jh["items"][5] and jh["items"][0]["photo"] and all(r["photo"] is None for r in jh["items"][1:])


def test_planned_counts_fill_same_angle_and_total_cap():
    main = [_a(k, k, "M") for k in "abcdef"]
    plan = _plan("L", [("L", "", [("a", "경위", None), ("b", "경위", None), ("c", "경위", None), ("d", "현장", None),
                                  ("e", "전망", None), ("f", "후임", None)])])
    secs = _secs(main)
    jonghap(secs, "종합", ROW, plan, None)
    assert [r["issue_id"] for r in secs[1]["items"]] == ["a", "d", "e", "f"]   # 각도 안 겹치게 4건
    two_angles = _plan("L", [("L", "", [("a", "경위", None), ("b", "경위", None), ("c", "현장", None), ("d", "현장", None)])])
    secs = _secs(main[:4])
    jonghap(secs, "종합", ROW, two_angles, None)
    assert [r["issue_id"] for r in secs[1]["items"]] == ["a", "b", "c"]        # 3건 채울 때만 같은 각도 (점수 순 유지)
    big = _plan("L", [("L", "", [(k, ang, None) for k, ang in zip("abcde", ("경위", "배경", "인물", "정책", "전망"))]),
                      ("S", "", [(k, ang, None) for k, ang in zip("xyz", ("현장", "쟁점", "전망"))])])
    secs = _secs([_a(k, k, "M") for k in "abcde"], [_a(k, k, "M") for k in "xyz"])
    jonghap(secs, "종합", ROW, big, secs[0]["items"][0])
    assert [(r["issue_id"], r["jh_group"]) for r in secs[1]["items"]] == [("a", 0), ("b", 0), ("c", 0), ("d", 0), ("x", 1), ("y", 1), ("z", 1)]   # 둘째가 있으면 메인 4
    one = _plan("L", [("L", "", [(k, ang, None) for k, ang in zip("abc", ("경위", "배경", "인물"))]), ("S", "", [("x", "현장", None), ("y", "현장", "x")])])
    secs = _secs([_a(k, k, "M") for k in "abc"], [_a(k, k, "M") for k in "xy"])
    jonghap(secs, "종합", ROW, one, secs[0]["items"][0])
    assert [r["jh_group"] for r in secs[1]["items"]] == [0, 0, 0]               # 둘째 1건 -> 둘째 묶음 없음 (메인은 그대로)
    secs = _secs([_a(k, k, "M") for k in "ab"])
    jonghap(secs, "종합", ROW, _plan("L", [("L", "", [("a", "경위", None), ("b", "배경", None)])]), None)
    assert [s["id"] for s in secs] == ["front", "politics"]                     # 메인 2건 -> 종합면 없음


def test_no_plan_or_other_lead_falls_back_to_s47():
    angles = [_a("a", "베선트·러트닉 백악관 충돌", "중앙일보"), _a("b", "월가 목표가 하향", "한국경제"), _a("f", "美의회 수출통제", "한겨레")]
    for plan in (None, _plan("OTHER", [("OTHER", "x", [])])):
        secs = _secs(angles)
        jonghap(secs, "종합", ROW, plan, None)
        assert [r["issue_id"] for r in secs[1]["items"]] == ["a", "b", "f"] and secs[1]["theme"] == "젠슨 황 사임"
        assert not secs[1]["theme_named"] and all(r["jh_angle"] is None for r in secs[1]["items"])


def test_clean_plan_rules():
    lead = {"issue_id": "L"}
    cands = [{"issue_id": k} for k in "abcd"]
    res = {"groups": {"L": {"band": "아주 긴 묶음 이름이 열여섯 자를 넘는다", "angles": {
        "a": {"angle": "없는각도", "dup": False}, "b": {"angle": "현장", "dup": True, "dup_of": "zz"},
        "c": {"angle": "전망", "dup": True, "dup_of": "a"}}}}}
    plan = _clean_plan(res, [(lead, cands)])
    ang = plan["groups"][0]["angles"]
    assert ang["a"] == {"angle": "기타", "dup": False, "dup_of": None}
    assert ang["b"] == {"angle": "현장", "dup": False, "dup_of": None}
    assert ang["c"] == {"angle": "전망", "dup": True, "dup_of": "a"}
    assert ang["d"] == {"angle": "기타", "dup": False, "dup_of": None}
    assert len(plan["groups"][0]["band"]) == 16
    assert _clean_plan("not json", [(lead, cands)]) is None and _clean_plan({"groups": {}}, [(lead, [])]) is None


def _host_ed():
    def it(iid, title, angles=(), **kw):
        return {**_it(iid, "ko", title, "리드."), "angles": [_it(a, "en", f"angle {a}", "A lead.") for a in angles], "merged": [], **kw}
    return {"sections": {"front": [it("F1", "젠슨 황 사임", "abc", headline_by={"조선": [1, "naver_a1"], "동아": [1, "naver_a1"]}),
                                   it("F2", "젠슨 황 사임", "de"),        # 메인과 제목 같음 -> 건너뜀
                                   it("F3", "다른 이슈", "bx"),           # 메인 후보 b 와 겹침 -> 건너뜀
                                   it("F4", "메가프로젝트", "xy")],
                         "politics": [it("P1", "정치", "pq")]}, "compare": [], "stats": {}}


COUNTRY = {"조선": "KR", "동아": "KR", "S": "KR"}


def test_jonghap_hosts_second_rules():
    ed = _host_ed()
    lead, second, why = jonghap_hosts([(k, ed["sections"].get(k, [])) for k in ("front", "jonghap", "politics")], COUNTRY)
    assert lead["issue_id"] == "F1" and second["issue_id"] == "F4"


class _Cfg:
    analysis_model, analysis_timeout_sec = "opus", 10


def test_plan_jonghap_calls_once_caches_and_koreanizes_candidates():
    calls = []

    def guarded(prompt, **kw):
        calls.append(prompt)
        if "종합면 편집" in prompt:
            return {"groups": {"F1": {"band": "젠슨 황 사임 후폭풍", "angles": {"a": {"angle": "경위"}, "b": {"angle": "시장 반응", "dup": True, "dup_of": "F1"},
                                                                          "c": {"angle": "후임"}}},
                               "F4": {"band": "메가", "angles": {"x": {"angle": "현장"}, "y": {"angle": "쟁점"}}}}}, "ok"
        ids = re.findall(r'"id": "([^"]+)"', prompt)
        return {"items": {k: {"title": "한국어 " + k[0], "summary": "요약.", "deck": "부제"} for k in ids}}, "ok"

    ed, cache = _host_ed(), {}
    st = plan_jonghap(ed, DISP, cache, guarded, _Cfg, ["front", "jonghap", "politics"], COUNTRY)
    assert st["lead"] == "F1" and st["second"] == "F4" and st["dups"] == [{"id": "b", "of": "F1", "angle": "시장 반응"}]
    plan = ed["jonghap_plan"]
    assert plan["lead"] == "F1" and [g["host"] for g in plan["groups"]] == ["F1", "F4"]
    angles = ed["sections"]["front"][0]["angles"]
    assert angles[0]["llm"]["ko_title"] == "한국어 a" and "llm" not in angles[1]     # dup 후보는 한국어 안 받음
    assert len(calls) == 2
    ed2 = _host_ed()
    st2 = plan_jonghap(ed2, DISP, cache, guarded, _Cfg, ["front", "jonghap", "politics"], COUNTRY)
    assert st2["status"].startswith("캐시") and len(calls) == 2 and ed2["jonghap_plan"] == plan


def test_plan_failure_still_koreanizes_first_six():
    def guarded(prompt, **kw):
        if "종합면 편집" in prompt:
            return None, "호출 실패: x"
        ids = re.findall(r'"id": "([^"]+)"', prompt)
        return {"items": {k: {"title": "한국어", "summary": "요약.", "deck": ""} for k in ids}}, "ok"
    ed = _host_ed()
    ed["sections"]["front"][0]["angles"] = [_it(f"z{k}", "en", f"angle {k}", "A.") for k in range(8)]
    st = plan_jonghap(ed, DISP, {}, guarded, _Cfg, ["front", "politics"], COUNTRY)
    assert "jonghap_plan" not in ed and st["status"].startswith("호출 실패")
    got = [bool(a.get("llm", {}).get("ko_title")) for a in ed["sections"]["front"][0]["angles"]]
    assert got == [True] * 6 + [False] * 2



# ---------- 구현 리뷰 반영 ----------
def test_clean_plan_bad_shapes_and_missing_main_group():
    lead = {"issue_id": "L"}
    cands = [{"issue_id": "a"}, {"issue_id": "b"}]
    weird = {"groups": {"L": {"angles": {"a": {"angle": "경위", "dup": True, "dup_of": ["b"]}, "b": {"dup_of": {"x": 1}, "dup": True}}}}}
    plan = _clean_plan(weird, [(lead, cands)])                                   # 목록·dict dup_of 에도 예외 없음 (B1)
    assert plan["groups"][0]["angles"]["a"] == {"angle": "경위", "dup": False, "dup_of": None}
    assert _clean_plan({"groups": {}}, [(lead, cands)]) is None                  # 메인 묶음 답 없음 → 계획 없음 (B2)
    assert _clean_plan({"groups": {"WRONG": {}}}, [(lead, cands)]) is None


def test_pick_planned_dup_only_against_kept():
    """b 는 같은 각도라 안 실리므로, b 를 가리키는 c 는 남는다 (구현 리뷰 M2)."""
    main = [_a(k, k, "M") for k in "abcde"]
    plan = _plan("L", [("L", "x", [("a", "경위", None), ("b", "경위", None), ("c", "전망", "b"), ("d", "현장", None), ("e", "인물", None)])])
    secs = _secs(main)
    jonghap(secs, "종합", ROW, plan, None)
    assert [r["issue_id"] for r in secs[1]["items"]] == ["a", "c", "d", "e"]


def test_band_name_missing_still_counts():
    plan = _plan("L", [("L", "", [(k, ang, None) for k, ang in zip("abc", ("경위", "배경", "인물"))])])
    secs = _secs([_a(k, k, "M") for k in "abc"])
    jonghap(secs, "종합", ROW, plan, None)
    assert secs[1]["theme"] == "젠슨 황 사임" and secs[1]["theme_named"] is True   # 이름 없으면 메인 제목, "· 기사 n건" 은 보임 (M6)


def test_trim_lead_skips_abbreviations():
    assert trim_lead("The minister met Mr. Kim and the U.S. envoy. They discussed the trade deal and the") == \
        "The minister met Mr. Kim and the U.S. envoy. …"


def test_korean_pass_empty_deck_clears_old_and_empty_title_asked_again():
    ed = {"sections": {"international": [_it("i1", "en", "News", "L.", llm={"deck": "옛 부제"})]}, "compare": []}
    store = {}

    def g(prompt, **kw):
        ids = re.findall(r'"id": "([^"]+)"', prompt)
        return {"items": {k: {"title": "", "summary": "요약.", "deck": ""} for k in ids}}, "ok"
    korean_pass(ed, DISP, store, g)
    llm = ed["sections"]["international"][0]["llm"]
    assert "deck" not in llm and "ko_title" not in llm and llm["ko_summary"] == "요약."   # 빈 부제는 옛 부제를 지운다 (M5)
    ent = next(iter(store["korean"].values()))
    assert "title" not in ent and ent["deck"] == ""                                       # 빈 제목은 다음에 다시 (M8)


def test_unusable_angle_answer_not_cached():
    ed, cache, calls = _host_ed(), {}, []

    def g(prompt, **kw):
        calls.append(prompt)
        if "종합면 편집" in prompt:
            return {"groups": {}}, "ok"
        return {"items": {}}, "ok"
    plan_jonghap(ed, DISP, cache, g, _Cfg, ["front", "politics"], COUNTRY)
    assert "jonghap_plan" not in ed and "jonghap_angles" not in cache
    n = sum("종합면 편집" in c for c in calls)
    plan_jonghap(_host_ed(), DISP, cache, g, _Cfg, ["front", "politics"], COUNTRY)
    assert sum("종합면 편집" in c for c in calls) == n + 1                                # 다시 묻는다 (M8)


def test_jonghap_hosts_lead_outside_front():
    ed = _host_ed()
    ed["sections"]["politics"][0]["headline_by"] = {k: [1, "naver_a1"] for k in ("조선", "동아", "S")}
    ed["sections"]["politics"][0]["articles"][0]["source"] = "조선"
    ed["sections"]["front"][0]["headline_by"] = {}
    lead, second, _ = jonghap_hosts([(k, ed["sections"].get(k, [])) for k in ("front", "politics")], COUNTRY)
    assert lead["issue_id"] == "P1" and second["issue_id"] == "F1"              # 메인이 1면 밖이면 1면 첫 기사부터 둘째 조건


def test_reader_resolves_eight_angles():
    from pipeline.reader import page_urls
    ed = {"sections": {"front": [{**_it("F", "ko", "t"), "url": "u0", "angles": [{**_it(f"a{k}", "en", "x"), "url": f"https://news.google.com/{k}"} for k in range(9)]}]}}
    urls = page_urls(ed)
    assert sum(u.startswith("https://news.google.com/") for u in urls) == 8
