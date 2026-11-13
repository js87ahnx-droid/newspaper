"""S47 종합면: 1면 메인 이슈의 같은 사건 다른 기사 3~6건 (사용자 시안 A).

기준 (project-plan.md S47b):
- 합쳐진 이슈·같은 사건 이웃, 그리고 메인을 A1 에 실은 신문이 A2~A4면에 함께 실은 이슈(낱말 겹침)가 후보(angles)
- 낱말이 안 겹치는 A2~A4 이슈, 지면에 따로 실린 이슈는 후보 아님
- 후보에서 3~6건: 메인·서로와 다른 매체, 제목이 거의 같은 것은 하나만. 3건 미만이면 종합면 없음
- lead_pick 이 1면 톱이 아닌 기사를 메인으로 고르면 그 기사의 후보로
"""
from pipeline.edit import arrange, choose, edition_to_json
from pipeline.interest import build_interest_table
from pipeline.render import jonghap
from pipeline.score import score_issues
from tests.test_edit import CFG, build, interests_variant


def _scored():
    arts, issues = build()
    it = interests_variant("default")
    return arts, it, score_issues(issues, arts, CFG, build_interest_table(it), [])


def test_angles_from_near_merged_and_paper_pages():
    arts, it, scored = _scored()
    placed, stats = choose(scored, CFG, it)
    ed = arrange(placed, CFG, it, arts)
    host = ed.sections["front"][0]
    real = [q for ps in ed.sections.values() for q in ps if not q.reserve]   # 예비 기사는 쪽이 남을 때만 — 지면에 실린 것으로 안 봄
    on = {q.scored.issue.id for q in real} | {m.issue.id for q in real for m in q.merged} | {r.scored.issue.id for q in real for r in q.related}
    free = [s for s in scored if s.issue.id not in on]
    near_one, page_one, page_other = free[0], free[1], free[2]
    other_placed = next(q for q in ed.sections["front"][1:] + ed.sections["politics"] if not q.reserve)
    host.scored.issue.extra["near"] = [near_one.issue.id, other_placed.scored.issue.id]
    host.scored.headline_by = {"신문가": [1, "naver_a1"]}
    host.scored.signature = ["엔비디아", "젠슨"]
    page_one.pages_by, page_one.signature = {"신문가": "A3"}, ["엔비디아", "이사회"]
    page_other.pages_by, page_other.signature = {"신문가": "A4"}, ["메가프로젝트"]   # 낱말이 안 겹침 → 다른 이슈
    out = edition_to_json(ed, "2026-11-13", arts, stats, scored)
    item = next(x for x in out["sections"]["front"] if x["issue_id"] == host.scored.issue.id)
    got = [a["issue_id"] for a in item["angles"]]
    assert near_one.issue.id in got and page_one.issue.id in got
    assert page_other.issue.id not in got and other_placed.scored.issue.id not in got and host.scored.issue.id not in got
    finals = [a["scores"]["final"] for a in item["angles"]]
    assert finals == sorted(finals, reverse=True) and len(got) <= 8
    assert all("angles" not in x for x in out["sections"]["briefs"])
    # scored 를 안 주면 후보 없음 (옛 호출)
    assert all(x["angles"] == [] for x in edition_to_json(ed, "2026-11-13", arts, stats)["sections"]["front"])


def _a(iid, title, source):
    return {"issue_id": iid, "title": title, "source": source, "merged": [], "related": [], "photo": f"https://img.test/{iid}.jpg"}


def _sections(angles, lead_source="동아일보", others=()):
    lead = {**_a("L", "젠슨 황, 불륜 의혹 속 엔비디아 CEO 사임", lead_source), "angles": angles, "view": {"title": "젠슨 황 사임"}}
    return [{"id": "front", "items": [], "lead": lead}, {"id": "politics", "items": [_a(o, "다른 기사 " + o, "X") for o in others]}]


ROW = lambda a: dict(a)   # noqa: E731  render.row 대신 (보기 데이터는 이 시험과 무관)


def test_jonghap_picks_distinct_outlets_and_titles():
    angles = [_a("a", "베선트·러트닉 백악관 충돌… AI칩 제재 왜 안 했나", "중앙일보"),
              _a("b", "월가, 엔비디아 목표가 줄줄이 낮춰", "한국경제"),
              _a("c", "월가, 엔비디아 목표가 줄줄이 낮춰…서학개미 7조 증발", "매일경제"),   # 제목 거의 같음 → 뺌
              _a("d", "엔비디아 임시 CEO 에 크레스 CFO", "동아일보"),                       # 메인과 같은 매체 → 뺌
              _a("e", "이사회 끝내 돌아서… 사내 불륜에 엄격한 미국 기업", "한국경제"),        # 이미 고른 매체 → 뺌
              _a("f", "美의회 반도체 수출통제 목소리 커져", "한겨레"),
              _a("g", "다른 기사 g", "경향신문")]
    secs = _sections(angles, others=["g"])   # g 는 이미 정치면에 실림
    jonghap(secs, "종합", ROW)
    assert [s["id"] for s in secs] == ["front", "jonghap", "politics"]
    jh = secs[1]
    assert [r["issue_id"] for r in jh["items"]] == ["a", "b", "f"] and jh["theme"] == "젠슨 황 사임"
    assert jh["items"][0]["photo"] and all(r["photo"] is None for r in jh["items"][1:])


def test_jonghap_needs_three_and_caps_at_six():
    two = [_a("a", "반도체 수출 사상 최대", "A"), _a("b", "환율 급등 외환시장 불안", "B")]
    secs = _sections(two)
    jonghap(secs, "종합", ROW)
    assert [s["id"] for s in secs] == ["front", "politics"]
    three = two + [_a("c", "부동산 대책 발표", "C")]
    secs = _sections(three)
    jonghap(secs, "종합", ROW)
    assert len(secs[1]["items"]) == 3
    words = ["반도체 수출 사상 최대", "환율 급등 외환시장 불안", "부동산 대책 발표", "북한 미사일 발사", "여야 예산 협상",
             "의대 정원 갈등", "폭염 경보 확대", "프로야구 개막", "우주 발사체 성공"]
    many = [_a(str(k), w, f"매체{k}") for k, w in enumerate(words)]
    secs = _sections(many)
    jonghap(secs, "종합", ROW)
    assert len(secs[1]["items"]) == 6


def test_jonghap_follows_lead_pick_not_front_top():
    """메인이 다른 면에서 올라온 기사면 그 기사의 후보로 (front_single 이 정한 lead 를 그대로 쓴다)."""
    mine = [_a("x", "여야 예산안 협상 결렬", "MX"), _a("y", "대통령실 국회 시정연설 일정", "MY"), _a("z", "특검법 표결 앞두고 긴장", "MZ")]
    secs = _sections([_a("p", "반도체 수출 사상 최대", "TP"), _a("q", "환율 1500원 돌파", "TQ"), _a("r", "부동산 대책 발표", "TR")])
    secs[0]["lead"] = {**_a("P", "정치면에서 올라온 메인", "연합뉴스"), "angles": mine, "view": {"title": "정치 메인"}}
    jonghap(secs, "종합", ROW)
    assert [r["issue_id"] for r in secs[1]["items"]] == ["x", "y", "z"] and secs[1]["theme"] == "정치 메인"


def test_reserve_used_on_jonghap_leaves_briefs():
    """예비 기사(단신 맨 뒤)를 종합면에 쓰면 단신에서는 뺀다 — 같은 기사가 두 번 실리지 않게."""
    angles = [_a("a", "반도체 수출 사상 최대", "A"), _a("b", "환율 급등 외환시장 불안", "B"), _a("c", "부동산 대책 발표", "C")]
    secs = _sections(angles)
    secs.append({"id": "briefs", "items": [{**_a("b", "환율 급등 외환시장 불안", "B"), "reserve": True}, _a("k", "단신 하나", "K")]})
    jonghap(secs, "종합", ROW)
    assert [r["issue_id"] for r in secs[1]["items"]] == ["a", "b", "c"]
    assert [r["issue_id"] for r in secs[-1]["items"]] == ["k"]

