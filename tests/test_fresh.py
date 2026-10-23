"""실릴 기사 최신성 검증 (S28f, 2026-10-23 "실릴 기사를 가장 최신 뉴스와 비교 검증해 지난 내용을 한 번 더 거르기")."""
from pipeline.edit import Placed, arrange, choose
from pipeline.fresh import MAX_PAIRS, PER_ITEM, ai_stale, drop_and_promote, find_pairs
from tests.test_edit import CFG, _sc, run
from tests.test_market import _art

SIG = ["협상", "타결", "관세", "합의", "통상", "장관"]


def _issue(iid, title, sig, published, final=1.0, topic="economy"):
    s = _sc(iid, title, sig, final=final, topic=topic)
    s.issue.article_ids, s.issue.rep_article = [iid], iid
    return s, _art(iid, title, published)


def _world(extra=()):
    rows = [
        _issue("old", "한미 관세 협상 막판 진통", SIG, "2026-10-22T03:00:00+00:00", final=3),
        _issue("new", "한미 관세 협상 타결…통상장관 합의문 서명", SIG, "2026-10-22T15:00:00+00:00", final=1),
        _issue("soon", "관세 협상 장관 회의 속개", SIG, "2026-10-22T03:30:00+00:00"),      # 30분 뒤 — 1시간 안 됨
        _issue("other", "프로야구 한국시리즈 1차전", ["야구", "시리", "즈1", "차전", "한국", "프로"], "2026-10-22T16:00:00+00:00"),
        *extra,
    ]
    scored = [r[0] for r in rows]
    arts = {r[1].id: r[1] for r in rows}
    sections = {"economy": [Placed(scored[0], [], "economy")], "briefs": []}
    return sections, scored, arts


def test_pairs_only_newer_same_story():
    sections, scored, arts = _world()
    pairs = find_pairs(sections, scored, arts)
    assert [(p.scored.issue.id, s.issue.id) for p, s in pairs] == [("old", "new")]


def test_pairs_caps():
    many = [_issue(f"n{k}", f"관세 협상 후속 {k}", SIG, "2026-10-22T15:00:00+00:00") for k in range(5)]
    sections, scored, arts = _world(many)
    assert len(find_pairs(sections, scored, arts)) == PER_ITEM
    hosts = [_issue(f"h{k}", f"관세 협상 지면 {k}", SIG, "2026-10-21T15:00:00+00:00", final=2) for k in range(MAX_PAIRS)]
    sections, scored, arts = _world(many + hosts)
    sections["economy"] += [Placed(h[0], [], "economy") for h in hosts]
    assert len(find_pairs(sections, scored, arts)) == MAX_PAIRS


def test_ai_stale_parses_and_survives_bad_answers():
    sections, scored, arts = _world()
    pairs = find_pairs(sections, scored, arts)
    seen = []

    def ask(prompt):
        seen.append(prompt)
        return {"stale": ["P0", "P9", "x"]}
    stale, st = ai_stale(pairs, arts, ask)
    assert stale == {0} and "지난 기사 1건" in st
    assert "지면 [10/22 12:00]" in seen[0] and "새 보도 [10/23 00:00]" in seen[0]   # 한국 시간으로 보여 준다
    assert ai_stale(pairs, arts, lambda p: None) == (set(), "응답 없음")
    assert ai_stale(pairs, arts, lambda p: {"stale": "P0"}) == (set(), "응답 없음")
    assert ai_stale([], arts, ask)[1] == "후보 없음"


def test_drop_and_promote_then_reedit_places_newer_report():
    _, scored, placed, _, ed, it = run("default")
    old = ed.sections["economy"][0]
    on_page = {p.scored.issue.id for ps in ed.sections.values() for p in ps}
    newer = min((s for s in scored if s.issue.id not in on_page), key=lambda s: s.final)   # 지면에 못 든 가장 낮은 이슈
    kept, notes = drop_and_promote(scored, [(old, newer)], {0})
    assert old.scored not in kept and newer.final >= old.scored.final and newer.topic == old.scored.topic and len(notes) == 1
    from tests.test_edit import _arts_of
    ed2 = arrange(choose(kept, CFG, it)[0], CFG, it, _arts_of(ed))
    ids = {p.scored.issue.id for ps in ed2.sections.values() for p in ps}
    assert newer.issue.id in ids and old.scored.issue.id not in ids


def test_dropped_story_kept_as_update_of_newer():
    """S29a: 지난 소식으로 빠진 기사는 이어받은 새 보도의 앞선 보도로 (흐름 누적 표시)."""
    sections, scored, arts = _world()
    pairs = find_pairs(sections, scored, arts)
    kept, _ = drop_and_promote(scored, pairs, {0}, arts)
    new = next(s for s in kept if s.issue.id == "new")
    assert [u["title"] for u in new.issue.extra["updates"]] == ["한미 관세 협상 막판 진통"]


def test_expired_check_in_same_call():
    """S29c: 시기성 판단은 최신성 검증과 같은 호출 한 번 — 발행 시각을 알려 주고, 고른 지면 기사 id 를 돌려준다."""
    from datetime import datetime, timezone
    from pipeline.fresh import ai_check
    sections, scored, arts = _world()
    pairs = find_pairs(sections, scored, arts)
    items = sections["economy"]
    calls = []

    def ask(prompt):
        calls.append(prompt)
        return {"stale": [], "expired": ["I0", "I7", "x"]}
    stale, expired, st = ai_check(pairs, items, arts, ask, ref=datetime(2026, 10, 22, 20, 30, tzinfo=timezone.utc))
    assert len(calls) == 1 and "10/23 05:30" in calls[0] and "I0\t" in calls[0] and "P0\t" in calls[0]
    assert stale == set() and expired == {"old"} and "지남 1건" in st
    assert ai_check(pairs, items, arts, lambda p: {"foo": 1})[2] == "응답 없음"
    assert ai_check(pairs, items, arts, lambda p: {"expired": "I0"})[2] == "응답 없음"
