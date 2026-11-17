"""S51 큐레이션 판 다듬기 — 11/17 호 피드백 8가지."""
from __future__ import annotations

from pipeline.render import related_opinions
from pipeline.textutil import fix_kana_tree, kana_to_hangul, opinion_key


# ---------- S51a 사설·칼럼 중복 (⑧) ----------
def test_opinion_key_same_piece_two_feeds():
    a = opinion_key("Wall Street Journal", "Opinion | Can Nvidia Thrive Without Jensen Huang?")
    b = opinion_key("Wall Street Journal", "Can Nvidia Thrive Without  Jensen Huang?")
    assert a == b
    assert opinion_key("Bloomberg", "Can Nvidia Thrive Without Jensen Huang?") != a   # 다른 매체는 다른 글


def test_related_opinions_dedupe_by_source_title():
    op = {"editorials": [], "columns": [
        {"issue_id": "X", "source": "Wall Street Journal", "kind": "column", "title": "Opinion | Can Nvidia Thrive Without Jensen Huang?",
         "url": "https://wsj.com/a?mod=rss_markets_main", "lean": "보수"},
        {"issue_id": "X", "source": "Wall Street Journal", "kind": "column", "title": "Can Nvidia Thrive Without Jensen Huang?",
         "url": "https://wsj.com/a?mod=rss_opinion", "lean": "보수"},
        {"issue_id": "X", "source": "Bloomberg", "kind": "column", "title": "Can Nvidia Thrive Without Jensen Huang?",
         "url": "https://bloomberg.com/b", "lean": "중도"},
        {"issue_id": "X", "source": "Wall Street Journal", "kind": "column", "title": "Another piece",
         "url": "https://wsj.com/a?mod=rss_opinion2", "lean": "보수"}]}
    got = [(o["source"], o["title"]) for o in related_opinions(op)["X"]]
    assert got == [("Wall Street Journal", "Opinion | Can Nvidia Thrive Without Jensen Huang?"),
                   ("Bloomberg", "Can Nvidia Thrive Without Jensen Huang?"), ("Wall Street Journal", "Another piece")]


def test_organize_dedupes_same_piece():
    from pipeline.opinion import dedupe_opinions

    class A:
        def __init__(self, src, title, kind):
            self.source, self.title, self.opinion = src, title, kind
    xs = [A("WSJ", "Opinion | X", "column"), A("WSJ", "X", "editorial"), A("WSJ", "Y", "column")]
    out = dedupe_opinions(xs)
    assert [(o.title, o.opinion) for o in out] == [("X", "editorial"), ("Y", "column")]   # 사설이 남고, 원래 순서
    assert len(dedupe_opinions([A("WSJ", "", "column"), A("WSJ", "", "column")])) == 2       # 빈 제목은 같은 글로 보지 않음


# ---------- S51b 가나 → 한글 (⑥) ----------
def test_kana_to_hangul():
    assert kana_to_hangul("라ム슈타인 그룹 회의") == "라무슈타인 그룹 회의"
    assert kana_to_hangul("방공 지원을 둘러싼 라ムシュ타인 회의 결과") == "방공 지원을 둘러싼 라무슈타인 회의 결과"
    assert kana_to_hangul("トランプ大統領、北朝鮮") == "トランプ大統領、北朝鮮"        # 한글 없는 원문은 그대로
    assert kana_to_hangul("東京・大阪 회담") == "東京・大阪 회담"                    # 가운뎃점은 그대로
    assert kana_to_hangul("チャ지ュ キョ ンン") == "차지유 쿄 은은"                # 원래 한글(지)에는 ュ 를 붙이지 않음
    assert kana_to_hangul("라ン 회의") == "라은 회의" and kana_to_hangul("ラン 회의") == "란 회의"   # 원래 한글엔 받침을 안 붙임
    assert kana_to_hangul("ヰヱヵヶ 회의") == "이에카케 회의"


def test_fix_kana_tree_only_changed_copied():
    ed = {"a": {"b": "라ム슈타인"}, "c": {"d": "그대로"}, "e": ["リビウ 방문", "ニュース"]}
    out = fix_kana_tree(ed)
    assert out["a"]["b"] == "라무슈타인" and out["e"] == ["리비우 방문", "ニュース"]
    assert out["c"] is ed["c"] and ed["a"]["b"] == "라ム슈타인"                      # 원본은 안 바뀜


# ---------- S51c 각도 후보 순서·무관 (②③) ----------
from pipeline.llm import _clean_plan  # noqa: E402
from pipeline.render import content_first, jonghap  # noqa: E402
from tests.test_s49 import ROW, _a, _plan, _secs  # noqa: E402


def test_content_first_keeps_all_and_order():
    xs = [{"issue_id": "a", "lead": ""}, {"issue_id": "b", "lead": "내용"}, {"issue_id": "c", "lead": "", "llm": {"ko_summary": "요약"}},
          {"issue_id": "d", "lead": " "}]
    assert [x["issue_id"] for x in content_first(xs)] == ["b", "c", "a", "d"]


def test_clean_plan_keeps_unrelated():
    lead, cands = {"issue_id": "L"}, [{"issue_id": "a"}, {"issue_id": "b"}]
    plan = _clean_plan({"groups": {"L": {"angles": {"a": {"angle": "무관"}, "b": {"angle": "현장"}}}}}, [(lead, cands)])
    assert plan["groups"][0]["angles"]["a"]["angle"] == "무관"


def test_pick_planned_drops_unrelated_and_puts_other_last():
    main = [{**_a(k, k, "M"), "lead": "내용."} for k in "abcde"]
    plan = _plan("L", [("L", "x", [("a", "기타", None), ("b", "무관", None), ("c", "현장", None), ("d", "전망", None), ("e", "배경", None)])])
    secs = _secs(main)
    jonghap(secs, "종합", ROW, plan, None)
    ids = [r["issue_id"] for r in secs[1]["items"]]
    assert "b" not in ids and ids[-1] == "a" and set(ids) == {"a", "c", "d", "e"}


def test_pick_planned_drops_other_without_content():
    main = [{**_a(k, k, "M"), "lead": "내용."} for k in "abcd"]
    main[0]["lead"] = ""                                                     # 기타 + 내용 없음 → 뺌
    main[1]["lead"] = ""                                                     # 현장 + 내용 없음 → 남음(원문 보기)
    plan = _plan("L", [("L", "x", [("a", "기타", None), ("b", "현장", None), ("c", "전망", None), ("d", "배경", None)])])
    secs = _secs(main)
    jonghap(secs, "종합", ROW, plan, None)
    ids = [r["issue_id"] for r in secs[1]["items"]]
    assert "a" not in ids and ids[-1] == "b"                                  # 내용 없는 후보는 뒤로


# ---------- S51d 종합면 접기 (②④) ----------
def test_curated_folds_jonghap_into_hosts():
    import copy
    from pipeline.render import build_context
    from pipeline.settings import load_config, load_interests, load_sources
    from tests.test_s49_browser import _site
    from tests.test_s50 import _edition
    ed = _edition(_site())
    args = (load_config(), load_interests(), load_sources())
    base = build_context(copy.deepcopy(ed), *args)["sections"]
    cur = build_context(copy.deepcopy(ed), *args, variant="b")["sections"]
    jh = next(s for s in base if s["id"] == "jonghap")["items"]
    g0 = [r["issue_id"] for r in jh if not r.get("jh_group")]
    g1 = [r["issue_id"] for r in jh if r.get("jh_group") == 1]
    assert g0 and not any(s["id"] == "jonghap" for s in cur)
    front = next(s for s in cur if s["id"] == "front")
    detail = next(s for s in cur if s["id"] == "detail")["items"][0]
    assert [r["issue_id"] for r in front["lead"]["angle_rows"]] == g0 == [r["issue_id"] for r in detail["angle_rows"]]
    assert all(r["angle"] and r["title"] for r in detail["angle_rows"])
    if g1:
        host = next(r for r in front["items"] if r.get("angle_rows"))
        assert [r["issue_id"] for r in host["angle_rows"]] == g1
    shown = {r["issue_id"] for s in cur for r in s["items"] if s["id"] not in ("detail", "curated_src")}
    assert not (set(g0 + g1) & shown)                                       # 접힌 기사는 지면에 따로 안 실림


# ---------- S51e 큐레이션 고르기 (⑦) ----------
from pipeline.llm import curate_rank  # noqa: E402
from pipeline.render import curate  # noqa: E402


class _K:
    keep = {"international": 3}
    list_max = 6


def _x(i, final, guaranteed=False):
    return {"issue_id": i, "title": "t" + i, "view": {"title": "t" + i}, "source": "S", "topic": "international", "url": "u" + i,
            "headline_by": {}, "pages_by": {}, "guaranteed": guaranteed, "scores": {"final": final}}


def test_fallback_international_by_score_not_guarantee():
    """11/17 국제면 꼴: 다양성 보장 기사(점수 낮음)가 종합 점수 높은 네타냐후를 밀어내지 않는다."""
    secs = [{"id": "international", "items": [_x("pope", .46), _x("bibi", .461), _x("eu", .45, True), _x("fire", .449, True), _x("harry", .404, True)]},
            {"id": "briefs", "items": []}]
    curate(secs, _K)
    assert [r["issue_id"] for r in secs[0]["items"]] == ["pope", "bibi", "eu"]
    assert [m["issue_id"] for m in secs[0]["more"]] == ["fire", "harry"]


def test_rank_order_used_and_shown_in_that_order():
    secs = [{"id": "international", "items": [_x("pope", .46), _x("bibi", .461), _x("eu", .45), _x("fire", .449), _x("brexit", .38)]},
            {"id": "briefs", "items": []}]
    curate(secs, _K, {"international": ["brexit", "bibi", "nope"]})
    assert [r["issue_id"] for r in secs[0]["items"]] == ["pope", "brexit", "bibi"]   # 머리 + AI 순서대로
    assert [m["issue_id"] for m in secs[0]["more"]] == ["eu", "fire"]                 # 빠진 것은 점수 순


def test_curate_rank_call_cache_and_bad_answer():
    ed = {"sections": {"international": [_x(k, .4) for k in "abcd"], "politics": [_x("p", .5)]}}
    calls = []

    def g(prompt, **kw):
        calls.append(prompt)
        return {"sections": {"international": ["d", "x", "b", "d", 3]}}, "ok"

    class Cfg:
        analysis_model, analysis_timeout_sec = "m", 10
    cache = {}
    assert curate_rank(ed, cache, g, Cfg, {"international": 3, "politics": 4}) == "ok (1면)"
    assert ed["curate_rank"] == {"international": ["d", "b"]} and len(calls) == 1
    assert '"면머리": true' in calls[0] and '"politics"' not in calls[0]            # 남길 수 이하 면은 묻지 않음
    ed2 = {"sections": ed["sections"]}
    assert curate_rank(ed2, cache, g, Cfg, {"international": 3}) == "캐시" and len(calls) == 1
    bad = {}
    assert curate_rank({"sections": ed["sections"]}, bad, lambda p, **k: ({"x": 1}, "ok"), Cfg, {"international": 3}) == "응답 이상"
    assert "curate_rank" not in bad


def test_fold_keeps_single_and_second_without_main():
    """접을 땐 3건 기준이 없다: 메인 1건이라도, 메인이 비어도 둘째 이슈 각도는 붙는다."""
    main = [{**_a("a", "a", "M"), "lead": "내용."}, {**_a("b", "b", "M"), "lead": ""}]
    sec_angles = [{**_a("x", "x", "N"), "lead": "내용."}]
    plan = _plan("L", [("L", "x", [("a", "현장", None), ("b", "기타", None)]), ("S", "둘째", [("x", "배경", None)])])
    secs = _secs(main, sec_angles)
    second = secs[0]["items"][0]
    jonghap(secs, "종합", ROW, plan, second, fold=True)
    assert not any(s["id"] == "jonghap" for s in secs)
    assert [r["issue_id"] for r in secs[0]["lead"]["angle_rows"]] == ["a"] and second["angle_rows"][0]["angle"] == "배경"



def test_rank_missing_ids_follow_fallback_paper_first():
    """AI 순위에 빠진 기사는 대체 규칙(국내 면: 신문 지면 신호 먼저) 순서로 (구현 리뷰 M6)."""
    class K:
        keep = {"politics": 3}
        list_max = 6
    paper = {**_x("p", .30), "headline_by": {"조선": [1, "naver_a1"]}, "topic": "politics"}
    secs = [{"id": "politics", "items": [_x("h", .5), _x("a", .45), _x("b", .44), paper]}, {"id": "briefs", "items": []}]
    curate(secs, K, {"politics": ["b"]})
    assert [r["issue_id"] for r in secs[0]["items"]] == ["h", "b", "p"]


def test_enrich_calls_curate_once_only_when_curated(tmp_path):
    """enrich 연결: curated_keep 이 있을 때만 큐레이션 순위 호출 1회, 없으면 0회·지난 순위는 지움 (구현 리뷰 M5)."""
    import json
    from datetime import date
    from pipeline.llm import Budget, enrich
    from pipeline.settings import Llm, load_interests

    def edition():
        its = [{"issue_id": f"i{k}", "title": f"기사 {k}", "lead": "리드.", "topic": "international", "scores": {"final": .5 - k / 100},
                "articles": [{"id": f"i{k}", "source": "S", "country": "US", "lean": "중도", "lang": "ko", "title": f"기사 {k}", "lead": "리드."}]}
               for k in range(6)]
        return {"sections": {"international": its}, "compare": [], "stats": {}, "curate_rank": {"old": ["x"]}}

    calls = []

    def runner(prompt):
        calls.append(prompt)
        body = {"sections": {"international": ["i5", "i4"]}} if "편집장" in prompt else {}
        return json.dumps({"result": json.dumps(body, ensure_ascii=False), "is_error": False})

    cfg = Llm(enabled=True, model="haiku", max_calls_per_day=50, timeout_sec=10, analysis_issues=0)
    disp = load_interests().foreign_display
    ed = enrich(edition(), cfg, disp, tmp_path / "a.json", Budget(tmp_path / "u.json", date(2026, 11, 17), 50), runner=runner,
                curated_keep={"international": 3})
    assert sum("편집장" in c for c in calls) == 1 and ed["curate_rank"] == {"international": ["i5", "i4"]}
    calls.clear()
    ed = enrich(edition(), cfg, disp, tmp_path / "b.json", Budget(tmp_path / "u2.json", date(2026, 11, 17), 50), runner=runner)
    assert sum("편집장" in c for c in calls) == 0 and "curate_rank" not in ed


def test_fold_counts_match_base_when_base_has_group():
    """같은 각도가 많을 때도 기존 판(3건 채움)과 접기 건수가 같다 (재리뷰 M1)."""
    main = [{**_a(k, k, "M"), "lead": "내용."} for k in "abcd"]
    plan = _plan("L", [("L", "x", [("a", "현장", None), ("b", "현장", None), ("c", "현장", None), ("d", "배경", None)])])
    base, cur = _secs(main), _secs([dict(x) for x in main])
    jonghap(base, "종합", ROW, plan, None)
    jonghap(cur, "종합", ROW, plan, None, fold=True)
    assert len(base[1]["items"]) == len(cur[0]["lead"]["angle_rows"]) == 3
