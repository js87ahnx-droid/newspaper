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
    assert [(o.title, o.opinion) for o in out] == [("X", "editorial"), ("Opinion | X", "column")][:1] + [("Y", "column")]


# ---------- S51b 가나 → 한글 (⑥) ----------
def test_kana_to_hangul():
    assert kana_to_hangul("라ム슈타인 그룹 회의") == "라무슈타인 그룹 회의"
    assert kana_to_hangul("방공 지원을 둘러싼 라ムシュ타인 회의 결과") == "방공 지원을 둘러싼 라무슈타인 회의 결과"
    assert kana_to_hangul("トランプ大統領、北朝鮮") == "トランプ大統領、北朝鮮"        # 한글 없는 원문은 그대로
    assert kana_to_hangul("東京・大阪 회담") == "東京・大阪 회담"                    # 가운뎃점은 그대로
    assert kana_to_hangul("チャ지ュ キョ ンン") == "차주 쿄 은은"


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
