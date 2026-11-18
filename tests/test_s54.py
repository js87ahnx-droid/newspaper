"""S54 11/18 호 피드백: ⑥ 사설 같은 주제 묶기 외. 사설 제목·리드는 모두 지어낸 글."""
from __future__ import annotations

import json

from pipeline.llm import edtopic_key, editorial_topics, parse_edtopics
from pipeline.opinion import organize
from pipeline.settings import load_config
from tests.test_opinion import art

ED = "editorial"


def _eds():
    """지어낸 사설 20건: 시험 부정행위 대책 6건(낱말이 서로 다름), 나머지는 각자 다른 사안."""
    cheat = [
        art(1, "조선일보", "보수", "[사설] 단추 구멍까지 막겠다는 감독 대책, 요행에 기대나", opinion=ED),
        art(2, "중앙일보", "보수", "[사설] 학생끼리 서로 지켜보라는 게 교육인가", opinion=ED),
        art(3, "경향신문", "진보", "[사설] 이틀 앞두고 급조한 부정 방지책, 혼선 없게 하라", opinion=ED),
        art(4, "한겨레", "진보", "[사설] 강화된 기기 반입 금지, 빈틈없이 시행하길", opinion=ED),
        art(5, "한국경제", "경제지", "[사설] 비상 걸린 시험장, 정부 위기 대응력 시험대", opinion=ED),
        art(6, "매일경제", "경제지", "감독관에게 책임 떠넘긴 오락가락 대책 [사설]", opinion=ED),
    ]
    other = [art(10 + i, src, ln, f"[사설] 다른 사안 {i} 제목 {w}", opinion=ED) for i, (src, ln, w) in enumerate([
        ("조선일보", "보수", "구단 관중"), ("조선일보", "보수", "특검법 침묵"), ("중앙일보", "보수", "빚 갚은 사람"),
        ("동아일보", "보수", "출연료"), ("동아일보", "보수", "수출 1조"), ("경향신문", "진보", "여당 내분"),
        ("한겨레", "진보", "법관회의"), ("한국경제", "경제지", "좀비기업"), ("매일경제", "경제지", "과징금"),
        ("한국경제", "경제지", "판결 탄핵"), ("중앙일보", "보수", "대리 의결"), ("한겨레", "진보", "기후 부채"),
        ("경향신문", "진보", "벤처 자금"), ("동아일보", "보수", "부실 징후")])]
    return cheat + other


def _edition():
    return {"sections": {"front": [], "politics": []}}


def _cmp_ids(op):
    return [sorted(e["id"] for g in c["groups"] for e in g["editorials"]) for c in op["compare"]]


def test_hint_groups_same_topic_editorials():
    eds = _eds()
    hint = {e.id: (1 if int(e.id[1:]) <= 6 else 100 + int(e.id[1:])) for e in eds}
    op = organize(eds, _edition(), None, topic_hint=hint)
    cheat = sorted(f"a{i}" for i in range(1, 7))
    assert cheat in _cmp_ids(op)
    grp = next(c for c in op["compare"] if sorted(e["id"] for g in c["groups"] for e in g["editorials"]) == cheat)
    assert {g["lean"] for g in grp["groups"]} == {"보수", "진보", "경제지"}
    assert not {r["id"] for r in op["editorials"]} & set(cheat)                       # 남은 사설 목록에 없음


def test_hint_none_or_empty_same_as_before():
    eds = _eds()
    base = organize(eds, _edition(), None)
    assert organize(eds, _edition(), None, topic_hint=None) == base
    assert organize(eds, _edition(), None, topic_hint={}) == base
    assert organize(eds, _edition(), None, topic_hint={"zzz": 1}) == base              # 모르는 id 만


def test_ai_groups_win_over_tfidf_and_issue_links():
    """{A,C}{B,D} 로 낱말이 겹치고 C·D 가 같은 지면 이슈에 이어져도, AI 가 A·B 같음·C·D 따로면 {A,B} 하나만."""
    a = art(1, "조선일보", "보수", "[사설] 반도체 보조금 확대 서둘러야 반도체 보조금", opinion=ED)
    c = art(2, "한겨레", "진보", "[사설] 반도체 보조금 확대 서둘러야 반도체 보조금 논란", opinion=ED)
    b = art(3, "경향신문", "진보", "[사설] 금리 동결 이후 가계부채 금리 동결", opinion=ED)
    d = art(4, "동아일보", "보수", "[사설] 금리 동결 이후 가계부채 금리 동결 우려", opinion=ED)
    eds = [a, b, c, d]
    base = organize(eds, _edition(), None)
    assert sorted(_cmp_ids(base)) == [["a1", "a2"], ["a3", "a4"]]                     # TF-IDF 만이면 {A,C}{B,D}
    t = "반도체 보조금 확대 서둘러야 논란 금리 동결 이후 가계부채 우려"
    edition = {"sections": {"front": [{"issue_id": "i1", "title": t, "articles": [{"title": t, "lead": t, "lang": "ko"}]}]}}
    op = organize(eds, edition, None, topic_hint={"a1": 1, "a3": 1, "a2": 2, "a4": 3})
    assert _cmp_ids(op) == [["a1", "a3"]]
    assert {r["id"] for r in op["editorials"]} == {"a2", "a4"}


def test_single_lean_ai_group_not_compared():
    eds = [art(1, "조선일보", "보수", "[사설] 가", opinion=ED), art(2, "동아일보", "보수", "[사설] 나", opinion=ED)]
    op = organize(eds, _edition(), None, topic_hint={"a1": 1, "a2": 1})
    assert op["compare"] == [] and {r["id"] for r in op["editorials"]} == {"a1", "a2"}


def test_parse_edtopics():
    ids = ["a", "b", "c"]
    assert parse_edtopics({"topics": {"a": 1, "b": "1", "x": 2, "c": "z"}}, ids) == {"a": 1, "b": 1}
    assert parse_edtopics({"topics": {"x": 1}}, ids) is None
    assert parse_edtopics({"nope": 1}, ids) is None and parse_edtopics(None, ids) is None


class _Budget:
    def __init__(self):
        self.n = 0
        self.used = 0
        self.spent = {}

    def take(self):
        self.n += 1
        return True

    def add(self, *a, **k):
        pass


def test_editorial_topics_calls_once_and_caches(tmp_path, monkeypatch):
    cfg = load_config().llm
    rows = [{"id": "a", "매체": "x", "제목": "t1", "리드": ""}, {"id": "b", "매체": "y", "제목": "t2", "리드": ""}]
    calls = []

    def fake_call(prompt, c, budget, runner=None, **kw):
        calls.append(kw)
        return {"topics": {"a": 1, "b": 1}}, "ok"
    import pipeline.llm as L
    monkeypatch.setattr(L, "call", fake_call)
    path = tmp_path / "x.llm.json"
    hint, st = editorial_topics(rows, cfg, _Budget(), path)
    assert hint == {"a": 1, "b": 1} and st.startswith("ok") and calls[0]["model"] == cfg.analysis_model
    assert calls[0]["timeout"] == cfg.analysis_timeout_sec
    assert json.loads(path.read_text(encoding="utf-8"))["ed_topics"][edtopic_key(["a", "b"])] == {"a": 1, "b": 1}
    hint2, st2 = editorial_topics(rows, cfg, _Budget(), path)
    assert hint2 == hint and st2 == "캐시" and len(calls) == 1
    # 응답 이상은 캐시에 안 쓴다
    monkeypatch.setattr(L, "call", lambda *a, **k: ({"topics": {"q": 1}}, "ok"))
    rows2 = rows + [{"id": "c", "매체": "z", "제목": "t3", "리드": ""}]
    hint3, st3 = editorial_topics(rows2, cfg, _Budget(), path)
    assert hint3 is None and st3 == "응답 이상"
    assert edtopic_key(["a", "b", "c"]) not in json.loads(path.read_text(encoding="utf-8"))["ed_topics"]


# ---------- S54b ⑤ 경제 분야 상한 (본선·예비) ----------
def _econ_heavy():
    import math
    from pipeline.edit import choose
    from pipeline.interest import build_interest_table
    from pipeline.score import score_issues
    from pipeline.settings import load_interests
    from tests.test_edit import build
    cfg, interests = load_config(), load_interests()
    arts, issues = build(160)
    scored = score_issues(issues, arts, cfg, build_interest_table(interests), [])
    for k, s in enumerate(sorted(scored, key=lambda s: -s.final)):
        if k % 3 != 2:   # 점수 상위의 2/3 를 경제로 — 경제 후보가 넘치는 날
            s.topic = "economy"
    placed, st = choose(scored, cfg, interests)
    return cfg, placed, st, math


def test_economy_cap_in_fill_and_reserves():
    cfg, placed, st, math = _econ_heavy()
    ed = cfg.editing
    assert ed.topic_max_ratio["economy"] == 0.30
    n = st["target"]
    main = [p for p in placed if not p.reserve]
    econ_fill = [p for p in main if p.scored.topic == "economy" and not p.guaranteed]
    econ_all = [p for p in main if p.scored.topic == "economy"]
    assert len(econ_all) <= max(math.floor(0.30 * n), sum(1 for p in econ_all if p.guaranteed)), (len(econ_all), n)
    assert econ_fill                                                                # 상한 안에선 경제도 들어감
    res = [p for p in placed if p.reserve and not p.filler]
    assert sum(p.scored.topic == "economy" for p in res) <= math.floor(0.30 * ed.reserve)
    assert len(main) == n                                                           # 전체 수 그대로 (다른 분야가 채움)


def test_editing_panel_lists_all_topic_caps():
    js = open("static/editing.js", encoding="utf-8").read()
    assert "Object.keys(r.topicMax" in js and "분야별로" in js
