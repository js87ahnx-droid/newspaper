"""S6 편집 규칙 검증 — 합성 데이터로 (실제 수집 데이터는 저장소에 없으므로).

기준 (project-plan.md S6):
- 관심도를 0 / 기본 / 극단으로 바꿔도 1면 톱이 같다
- 극단 관심 설정에서도 다양성 슬롯 ≥ 30%, 관심 기사 ≤ 50%
- 가짜 history 로 3일째 이슈는 관심도 0 이어도 단신 이상에 실리고 "3일째"
- 기사마다 배치 이유(점수 구성)가 있다
- 사진: 1면 2장, 섹션당 1장 상한
"""
import json
import random

import pytest

from pipeline.cluster import Issue
from pipeline.collect import Article
from pipeline.edit import arrange, choose, edition_to_json
from pipeline.interest import build_interest_table
from pipeline.score import load_previous, score_issues, write_history
from pipeline.settings import Interests, load_config, load_interests

CFG = load_config()

SOURCES = [  # (매체, 국가, 성향, 가중치, 언어)
    ("조선일보", "KR", "보수", 1.0, "ko"), ("한겨레", "KR", "진보", 0.9, "ko"), ("연합뉴스", "KR", "통신·공영", 1.0, "ko"),
    ("동아일보", "KR", "보수", 1.0, "ko"), ("경향신문", "KR", "진보", 0.9, "ko"), ("한국경제", "KR", "경제지", 0.9, "ko"),
    ("BBC", "UK", "통신·공영", 1.0, "en"), ("New York Times", "US", "진보", 1.0, "en"), ("Fox News", "US", "보수", 0.8, "en"),
]
TEMPLATES = {
    "politics": "대통령 국회 청문회 {w}",
    "economy": "코스피 금리 물가 {w}",
    "semis_ai": "반도체 HBM 엔비디아 {w}",
    "entertainment_sports": "배우 드라마 시사회 {w}",
    "incidents": "흉기 체포 사고 {w}",
    "lifestyle_culture": "날씨 여행 축제 {w}",
    "society": "교육 노조 파업 {w}",
}


def unique_word(k: int) -> str:
    """이슈마다 겹치지 않는 세 글자 고유어 (연속성 토큰이 이슈별로 구별되게)."""
    base = 0xAC00
    return "".join(chr(base + ((k * 97 + j * 1013) % 11172)) for j in range(3))


def build(n_issues=90, seed=3):
    rnd = random.Random(seed)
    arts, issues = {}, []
    topics = list(TEMPLATES)
    for k in range(n_issues):
        topic = topics[k % len(topics)]
        word = f"{unique_word(k)} {unique_word(k + 5000)}"
        n_src = rnd.choice([1, 1, 1, 2, 3, 5, 7])
        srcs = rnd.sample(SOURCES, n_src)
        ids = []
        for j, (name, country, lean, w, lang) in enumerate(srcs):
            aid = f"a{k}_{j}"
            title = TEMPLATES[topic].format(w=word) if lang == "ko" else f"President parliament {word}"
            arts[aid] = Article(
                id=aid, url=f"https://x.test/{aid}", source=name, country=country, lean=lean, media_type="종합지",
                weight=w, paywall=False, kind="rss", title=title, lead="리드", lang=lang,
                published="2026-10-15T12:00:00+00:00", date_source="feed", sections=["top"], main=(j == 0 and k % 4 == 0),
                first_seen="2026-10-15T12:00:00+00:00", image=f"https://img.test/{aid}.jpg" if rnd.random() < 0.6 else None,
            )
            ids.append(aid)
        a0 = arts[ids[0]]
        issues.append(Issue(
            id=ids[0], article_ids=ids, title=a0.title, rep_article=ids[0],
            sources=sorted({arts[i].source for i in ids}), countries=sorted({arts[i].country for i in ids}),
            leans=sorted({arts[i].lean for i in ids}), langs=sorted({arts[i].lang for i in ids}), cohesion=1.0,
        ))
    return arts, issues


def interests_variant(kind: str) -> Interests:
    base = load_interests().model_dump()
    if kind == "zero":
        base.update(topics={}, keywords=[], less=[], default_weight=0, less_weight=0, keyword_boost=0)
    elif kind == "extreme":  # 연예·스포츠만 100배
        base.update(topics={"entertainment_sports": 100.0}, keywords=[], less=[], default_weight=0, less_weight=0)
    return Interests.model_validate(base)


def run(kind="default", previous=None, mode=None):
    arts, issues = build(260)   # 하루 60건 + 예비 180건이 다 차도록 (S19d·S20)
    cfg = CFG.model_copy(deep=True)
    if mode:
        cfg.editing.interest_cap_mode = mode
    it = interests_variant(kind)
    scored = score_issues(issues, arts, cfg, build_interest_table(it), previous or [])
    placed, stats = choose(scored, cfg, it)
    ed = arrange(placed, cfg, it, arts)
    return arts, scored, placed, stats, ed, it


def test_front_top_independent_of_interest():
    tops = set()
    for kind in ("zero", "default", "extreme"):
        _, _, _, _, ed, _ = run(kind)
        tops.add(ed.sections["front"][0].scored.issue.id)
    assert len(tops) == 1


@pytest.mark.parametrize("mode", ["driven", "topic"])
def test_extreme_interest_keeps_diversity_and_cap(mode):
    _, scored, placed, stats, ed, it = run("extreme", mode=mode)
    n = it.daily_articles
    in_paper = [p for sid, ps in ed.sections.items() for p in ps if not p.reserve]   # 예비 기사는 하루 분량 밖
    filled = [p for p in in_paper if any(r.startswith("면 최소") for r in p.reasons)]   # S23a: 면 최소로 하루 분량 밖에서 채운 것
    assert len(in_paper) - len(filled) == n and len(filled) == ed.stats["section_min_filled"]
    in_paper = [p for p in in_paper if p not in filled]
    reserves = [p for ps in ed.sections.values() for p in ps if p.reserve]
    assert CFG.editing.reserve - len(filled) <= len(reserves) <= CFG.editing.reserve and all(p.section == "briefs" for p in reserves)
    assert min(p.scored.final for p in in_paper if not p.guaranteed) >= max(p.scored.final for p in reserves) - 1e-9 or mode == "topic"
    diverse = [p for p in in_paper if any(r.startswith(("다양성", "1면 톱")) for r in p.reasons)]
    assert len(diverse) / n >= CFG.editing.diversity_ratio
    # 다양성 슬롯은 관심도와 무관하게 주목도 상위여야 한다
    by_att = sorted(scored, key=lambda s: (-s.attention, -s.importance, s.issue.id))
    top_att = {s.issue.id for s in by_att[: len(diverse)]}
    assert {p.scored.issue.id for p in diverse} <= top_att | {ed.sections["front"][0].scored.issue.id}
    assert stats["interest_counted"] <= stats["interest_cap"] == int(CFG.editing.interest_cap * n)
    if mode == "topic":
        ent = [p for p in in_paper if p.scored.topic == "entertainment_sports"]
        assert len(ent) <= n * CFG.editing.interest_cap + len(diverse)


def test_extreme_interest_actually_shifts_paper_within_cap():
    """관심도가 바뀌면 지면이 달라지되(학습 효과) 상한을 넘지 않는다."""
    _, _, _, s0, ed0, _ = run("zero")
    _, _, _, s1, ed1, _ = run("extreme")
    ids0 = {p.scored.issue.id for ps in ed0.sections.values() for p in ps}
    ids1 = {p.scored.issue.id for ps in ed1.sections.values() for p in ps}
    assert ids0 != ids1
    assert s1["interest_counted"] > 0


def test_three_day_issue_guaranteed_even_without_interest(tmp_path):
    arts, issues = build()
    # 가장 점수가 낮을 법한 이슈(매체 1곳, 생활·문화)를 골라 전날까지 2일 이어졌다고 기록
    target = next(i for i in issues if len(i.article_ids) == 1 and "날씨" in i.title)
    from pipeline.score import issue_signature, title_df

    all_arts = list(arts.values())
    sig = issue_signature([arts[target.rep_article]], title_df(all_arts), len(all_arts))
    (tmp_path / "2026-10-15.json").write_text(
        json.dumps({"edition": "2026-10-15", "issues": [{"id": "old", "title": "전날", "topic": "lifestyle_culture",
                                                          "days": 2, "signature": sig}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    from datetime import date

    _, previous = load_previous(tmp_path, date(2026, 10, 16))
    _, scored, placed, _, ed, _ = run("zero", previous=previous)
    hit = [p for ps in ed.sections.values() for p in ps if p.scored.issue.id == target.id]
    assert hit, "3일째 이슈가 지면에 없다"
    assert hit[0].scored.days == 3
    assert any(r == "연속 보도 3일째" for r in hit[0].reasons)


def test_every_item_has_reasons_and_scores():
    arts, _, _, stats, ed, _ = run()
    out = edition_to_json(ed, "2026-10-16", arts, stats)
    items = [it for ps in out["sections"].values() for it in ps]
    assert items
    for it in items:
        assert it["reasons"]
        assert set(it["scores"]) == {"attention", "importance", "continuity", "interest", "final", "headline", "frontline"}
        assert all(0 <= v <= 1 for v in it["scores"].values())


def test_photo_caps_and_no_duplicates():
    _, _, _, _, ed, _ = run()
    assert sum(1 for p in ed.sections["front"] if p.photo) <= CFG.photos.front
    for sid in ("politics", "economy", "international", "interest", "briefs"):
        cap = 0 if sid == "briefs" else CFG.photos.per_section
        assert sum(1 for p in ed.sections[sid] if p.photo) <= cap
    ids = [p.scored.issue.id for ps in ed.sections.values() for p in ps]
    assert len(ids) == len(set(ids))


def test_history_has_no_body_or_lead(tmp_path):
    from datetime import date

    _, scored, _, _, ed, _ = run()
    placed_ids = {p.scored.issue.id for ps in ed.sections.values() for p in ps}
    path = write_history(tmp_path, date(2026, 10, 16), scored, placed_ids)
    data = json.loads(path.read_text(encoding="utf-8"))
    for x in data["issues"]:
        assert set(x) == {"id", "title", "topic", "days", "signature", "date", "timeline"}
        assert x["timeline"][-1] == {"date": "2026-10-16", "title": x["title"], "summary": None}
        assert all(set(t) == {"date", "title", "summary"} for t in x["timeline"])


def test_timeline_carried_from_previous_editions():
    """이어진 이슈는 앞선 호들의 경과(날짜·제목·요약)를 들고 온다. 옛 기록(timeline 없음)도 제목 한 줄로."""
    from pipeline.score import TIMELINE_MAX, past_timeline

    old = {"title": "옛 제목", "date": "2026-10-14", "days": 1, "signature": []}
    assert past_timeline(old) == [{"date": "2026-10-14", "title": "옛 제목", "summary": None}]
    prev = {"title": "어제 제목", "days": 2, "signature": [],
            "timeline": [{"date": f"2026-10-{d:02d}", "title": f"t{d}", "summary": "s"} for d in range(1, 12)]}
    tl = past_timeline(prev)
    assert len(tl) == TIMELINE_MAX and tl[-1]["date"] == "2026-10-11"
    assert past_timeline(None) == []


def test_latin_only_continuity_needs_three_words():
    from pipeline.score import continuity_match

    prev = [{"title": "China and North Korea to open bridge", "days": 1, "signature": ["north", "korea", "bridge", "open"]}]
    assert continuity_match(["north", "korea", "missile", "submarine"], prev) is None   # 두 낱말만 — 다른 사건
    assert continuity_match(["north", "korea", "bridge", "officially"], prev) is prev[0]
    assert continuity_match(["김지", "지용", "임명"], [{"title": "t", "days": 1, "signature": ["김지", "지용"]}])  # 한글은 그대로


def test_near_duplicate_issue_merged_not_placed_twice():
    """같은 사건 이웃(issue.extra["near"])이 이미 실렸으면 따로 싣지 않고 그 기사에 기사를 합친다. 빈 슬롯은 다음 이슈가 채운다."""
    arts, issues = build()
    it = interests_variant("default")
    scored = score_issues(issues, arts, CFG, build_interest_table(it), [])
    by_front = sorted(scored, key=lambda s: (-s.frontline, -s.attention, s.issue.id))
    top, dup = by_front[0], by_front[1]
    top.issue.extra["near"] = [dup.issue.id]
    dup.issue.extra["near"] = [top.issue.id]
    placed, stats = choose(scored, CFG, it)
    ids = {p.scored.issue.id for p in placed}
    assert dup.issue.id not in ids and stats["merged_duplicates"] == 1
    assert len([p for p in placed if not p.reserve]) == min(it.daily_articles, len(scored) - 1)
    host = next(p for p in placed if p.scored.issue.id == top.issue.id)
    ed = arrange(placed, CFG, it, arts)
    out = edition_to_json(ed, "2026-10-16", arts, stats)
    item = next(x for ps in out["sections"].values() for x in ps if x["issue_id"] == top.issue.id)
    assert item["merged"] == [dup.issue.id]
    assert {a["id"] for a in item["articles"]} == set(top.issue.article_ids) | set(dup.issue.article_ids)
    assert all("published" in a for a in item["articles"])
    assert host.merged == [dup]


def test_outlet_headlines_raise_front_and_final():
    """매체 머리기사(1면)로 오른 이슈는 1면 점수·최종 점수가 오르고, 여러 매체 1면이면 1면 톱이 된다 (S14b)."""
    arts, issues = build()
    it = interests_variant("default")
    base = score_issues(issues, arts, CFG, build_interest_table(it), [])
    multi = sorted((s for s in base if len({arts[i].source for i in s.issue.article_ids}) >= 2), key=lambda s: s.frontline)
    low = multi[len(multi) // 2]   # 1면 점수가 중간쯤인 이슈 (원래는 1면 밖)
    srcs = sorted({arts[i].source for i in low.issue.article_ids})
    heads = [{"source": s, "rank": 1, "title": "t", "via": "naver_a1",
              "article_id": next(i for i in low.issue.article_ids if arts[i].source == s)} for s in srcs]
    scored = score_issues(issues, arts, CFG, build_interest_table(it), [], heads)
    s = next(x for x in scored if x.issue.id == low.issue.id)
    b = next(x for x in base if x.issue.id == low.issue.id)
    assert s.headline > 0.8 and s.frontline > b.frontline and s.final > b.final   # 세 곳 1면 머리 → 1-exp(-3/1.5)
    assert s.headline_by == {src: [1, "naver_a1"] for src in srcs}
    assert all(x.headline == 0 for x in scored if x.issue.id != low.issue.id)
    placed, _ = choose(scored, CFG, it)
    ed = arrange(placed, CFG, it, arts)
    front = {p.scored.issue.id for p in ed.sections["front"]}
    assert low.issue.id in front   # 세 곳 1면 머리면 1면에 오른다
    ed0 = arrange(choose(base, CFG, it)[0], CFG, it, arts)
    assert low.issue.id not in {p.scored.issue.id for p in ed0.sections["front"]}   # 머리기사 정보 없이는 1면 밖


# ---------- S21 분야 분류·면 구성·호 단위 예산 ----------
def test_ai_topics_override_cache_and_fallback():
    """AI 분류(S21b): 틀린 분야 이름·목록에 없는 id 는 버리고(규칙에 맡김), 캐시된 이슈는 다시 묻지 않으며, 100건씩 나눈다."""
    from pipeline.topics import AI_TOPIC_BATCH, ai_topics
    rows = [{"id": f"i{k}", "titles": [f"t{k}"]} for k in range(AI_TOPIC_BATCH + 5)]
    asked = []

    def ask(prompt):
        asked.append(prompt)
        ids = [l.split("\t")[0] for l in prompt.split("<data>\n")[1].split("\n</data>")[0].split("\n")]
        out = {i: "society" for i in ids}
        out[ids[0]] = "weird"          # 없는 분야 → 버림
        out["zzz"] = "politics"        # 묻지 않은 id → 버림
        return {"topics": out}
    cache = {"i3": "science"}
    got, st = ai_topics(rows, ask, cache)
    assert len(asked) == 2                                   # 104건 → 100 + 4
    assert "\ni3\t" not in asked[0] and got["i3"] == "science"  # 캐시
    assert "i0" not in got and "zzz" not in got and got["i1"] == "society"
    assert st.count("/") == 2
    got2, _ = ai_topics(rows, lambda p: None, cache)
    assert got2 == {k: v for k, v in cache.items() if k in {r["id"] for r in rows}}   # 실패해도 캐시분은 쓴다
    assert ai_topics(rows[:3], lambda p: None, {})[0] == {}                          # 응답 없음 → 규칙


def test_topic_override_moves_issue_to_new_section_and_score():
    arts, issues = build()
    it = interests_variant("default")
    table = build_interest_table(it)
    base = score_issues(issues, arts, CFG, table, [])
    victim = next(s for s in base if s.topic == "politics")
    over = score_issues(issues, arts, CFG, table, [], topic_override={victim.issue.id: "science"})
    s2 = next(s for s in over if s.issue.id == victim.issue.id)
    assert s2.topic == "science" and s2.importance != victim.importance
    assert all(a.topic == b.topic for a, b in zip(base, over) if a.issue.id != victim.issue.id)


def test_society_section_and_interest_overflow():
    """S21c: 사회·과학 기사는 사회·과학 면으로, 자기 면이 다 찬 관심 분야 기사는 단신 대신 관심면으로."""
    _, scored, placed, stats, ed, it = run("default")
    soc = ed.sections.get("society", [])
    assert soc and all(p.scored.topic in ("society", "science") for p in soc)
    caps = {s.id: s.max_articles for s in CFG.sections}
    for sid in ("politics", "economy", "international"):
        if len(ed.sections[sid]) < caps[sid]:
            continue
        spill = [p for p in ed.sections["briefs"] if not p.reserve and p.scored.interest_hit
                 and p.scored.topic in ("politics", "economy", "international")]
        assert not spill or len(ed.sections["interest"]) >= caps["interest"]   # 관심면이 다 차야만 단신으로
    # 단신으로 간 지면 기사는 자기 면이 없는 분야이거나, 자기 면이 다 차고(관심 기사면 관심면까지) 넘친 것뿐
    from pipeline.edit import TOPIC_SECTION
    full = lambda sid: len(ed.sections.get(sid, [])) >= caps.get(sid, 0)  # noqa: E731
    for p in (p for p in ed.sections["briefs"] if not p.reserve):
        sec = TOPIC_SECTION.get(p.scored.topic)
        assert sec is None or (full(sec) and (not p.scored.interest_hit or full("interest"))), (p.scored.topic, sec)


def test_llm_budget_is_per_edition_not_utc_today(tmp_path):
    """S21a: 호출 상한은 호 날짜로 센다 — 전날(UTC) 재발행이 쓴 호출이 다음 호를 막지 않는다."""
    from datetime import date as _d
    from pathlib import Path as _P
    from pipeline.llm import Budget
    b = Budget(tmp_path / "u.json", _d(2026, 10, 17), 2)
    assert b.take() and b.take() and not b.take()
    assert Budget(tmp_path / "u.json", _d(2026, 10, 18), 2).take()
    src = (_P(__file__).parent.parent / "pipeline" / "__main__.py").read_text(encoding="utf-8")
    assert "Budget(" in src and "_date.today()" not in src and "date.today()" not in src


def test_continuity_guarantee_capped_and_skips_less_topics():
    """S21c: 연속 보장은 지면의 continuity_max_ratio 까지, '덜 보기' 분야는 보장하지 않는다."""
    arts, issues = build(260)
    it = interests_variant("default")
    prev = [{"id": f"p{k}", "title": "t", "topic": s_topic, "days": 5, "signature": [], "date": "2026-10-17", "timeline": []}
            for k, s_topic in enumerate(["x"])]
    scored = score_issues(issues, arts, CFG, build_interest_table(it), prev)
    for s in scored:          # 모든 이슈가 5일째 이어졌다고 치면
        s.days = 5
    placed, _ = choose(scored, CFG, it)
    cont = [p for p in placed if any(r.startswith("연속") for r in p.reasons)]
    import math
    assert 0 < len(cont) <= math.floor(CFG.editing.continuity_max_ratio * it.daily_articles)
    assert not any(p.scored.topic in it.less for p in cont)


# ---------- S23a 면별 최소 ----------

def _weak_society(keep: int | None = None):
    """사회 기사 점수를 바닥으로 (주말 10/18호처럼 하루 분량·예비에 못 듦). keep 이면 사회 기사를 그 수만 남긴다."""
    arts, issues = build(260)
    it = interests_variant("default")
    scored = score_issues(issues, arts, CFG, build_interest_table(it), [])
    soc = [s for s in scored if s.topic in ("society", "science")]
    if keep is not None:
        drop = {s.issue.id for s in soc[keep:]}
        scored = [s for s in scored if s.issue.id not in drop]
        soc = soc[:keep]
    for k, s in enumerate(soc):
        s.final = s.final_no_interest = -1.0 - k * 0.01
        s.attention = s.frontline = -1.0
        s.interest_hit = False
        s.days = 1
    return arts, it, scored


def _edit(arts, it, scored, section_min):
    cfg = CFG.model_copy(deep=True)
    cfg.editing.section_min = section_min
    placed, stats = choose(scored, cfg, it)
    return arrange(placed, cfg, it, arts), stats


def test_section_min_fills_short_section_from_candidates():
    """S23a: 점수가 낮아 비던 사회·과학 면도 2건. 채운 기사는 보장, 예비·단신에 두 번 나오지 않음."""
    arts, it, scored = _weak_society()
    ed0, _ = _edit(arts, it, scored, 0)
    assert len(ed0.sections["society"]) == 0          # 최소가 없으면 빈다 (재현)
    ed, stats = _edit(arts, it, scored, 2)
    from pipeline.edit import MIN_SECTIONS
    for sec in MIN_SECTIONS:
        assert len(ed.sections[sec]) >= 2, (sec, len(ed.sections[sec]))
    soc = ed.sections["society"]
    assert all(p.guaranteed and not p.reserve and "면 최소 2건" in p.reasons for p in soc)
    assert [p.scored.final for p in soc] == sorted((p.scored.final for p in soc), reverse=True)
    assert soc[0].scored.final == max(s.final for s in scored if s.topic in ("society", "science"))   # 그 면 최고점부터
    ids = [p.scored.issue.id for ps in ed.sections.values() for p in ps]
    assert len(ids) == len(set(ids))
    assert ed.stats["section_min_filled"] >= 2 and stats["section_fillers"] >= 2


@pytest.mark.parametrize("keep,expect", [(1, 1), (0, 0)])
def test_section_min_with_too_few_candidates(keep, expect):
    """S23a: 그 분야 후보가 1건뿐이면 1건, 없으면 0건 (오류 없음)."""
    arts, it, scored = _weak_society(keep)
    ed, _ = _edit(arts, it, scored, 2)
    assert len(ed.sections["society"]) == expect


def test_section_min_skips_same_event_neighbours():
    """S23a: 같은 사건이 이미 실린 후보는 채우지 않는다."""
    arts, it, scored = _weak_society()
    ed0, _ = _edit(arts, it, scored, 0)
    host = ed0.sections["politics"][0].scored.issue.id
    soc = sorted((s for s in scored if s.topic in ("society", "science")), key=lambda s: -s.final)
    soc[0].issue.extra["near"] = [host]               # 사회 1위 후보는 정치면 기사와 같은 사건
    ed, _ = _edit(arts, it, scored, 2)
    got = [p.scored.issue.id for p in ed.sections["society"]]
    assert soc[0].issue.id not in got and len(got) == 2


# ---------- S22b 관련 기사 ----------
def test_attach_related_moves_brief_under_host():
    from pipeline.edit import RELATED_MAX, attach_related
    _, scored, placed, stats, ed, it = run("default")
    host = ed.sections["politics"][0]
    briefs = list(ed.sections["briefs"])
    links = {b.scored.issue.id: host.scored.issue.id for b in briefs[: RELATED_MAX + 2]}
    links["없는"] = host.scored.issue.id
    n = attach_related(ed.sections, links)
    assert n == RELATED_MAX and len(host.related) == RELATED_MAX           # 기사당 상한
    moved = {r.scored.issue.id for r in host.related}
    left = {b.scored.issue.id for b in ed.sections["briefs"]}
    assert not moved & left                                                # 단신에서 빠짐
    assert not {b.scored.issue.id for b in briefs[: RELATED_MAX + 2]} & left  # 상한을 넘은 이어진 기사도 단신에 안 남음 (S24c)
    out = edition_to_json(ed, "2026-10-18", _arts_of(ed), stats)
    rel = next(i for i in out["sections"]["politics"] if i["issue_id"] == host.scored.issue.id)["related"]
    assert {r["issue_id"] for r in rel} == moved


def _arts_of(ed):
    arts, _ = build(260)
    return arts


def test_ai_related_parses_and_ignores_bad_ids():
    from pipeline.topics import ai_related
    hosts = [{"id": "h0", "title": "A"}, {"id": "h1", "title": "B"}]
    briefs = [{"id": "b0", "title": "a2"}, {"id": "b1", "title": "x"}]
    ans = iter([{"links": {"B0": "H1", "B1": "H0", "B7": "H0", "B9": "Hx"}}, {"keep": ["P0", "p9"]}])
    got, st = ai_related(hosts, briefs, lambda p: next(ans))
    assert got == {"b0": "h1"} and "검증 1" in st                       # 검증에서 b1 은 지워짐, 틀린 번호는 버림
    ans2 = iter([{"links": {"B0": "H1"}}, None])
    assert ai_related(hosts, briefs, lambda p: next(ans2))[0] == {}      # 검증 실패면 쓰지 않음
    assert ai_related(hosts, briefs, lambda p: None) == ({}, "응답 없음")
    assert ai_related([], briefs, lambda p: 1/0) == ({}, "후보 없음")


# ---------- S28d 관련 기사 오배치 (10/23호 실제 시그니처) ----------
def _sc(iid, title, sig, final=1.0, topic="economy"):
    from pipeline.score import ScoredIssue
    iss = Issue(id=iid, article_ids=[], title=title, rep_article="", sources=[], countries=[], leans=[], langs=["ko"], cohesion=1.0)
    return ScoredIssue(issue=iss, topic=topic, attention=0, importance=0, continuity=0, interest=0, final=final,
                       frontline=0, final_no_interest=0, days=1, interest_hit=False, signature=list(sig))


SPACEX = ("1f74", "뉴욕증시, 스페이스X 실적에 기술주 강세…나스닥 1.1%↑(종합)",
          ['나스', '스페', '페이', '스닥', '욕증', '이스', '뉴욕', '증시', '술주', '강세', '적에', '상승'])
KOSDAQ = ("7926", "한국거래소, 코스닥 승강제 최상위에 절대평가제 도입 검토",
          ['대평', '승강', '강제', '절대', '평가', '스닥', '코스', '최상', '래소', '상위', '도입', '거래'])
NY_BRIEFS = [
    ("e957", "뉴욕증시, AI 불안에 하락 출발", ['뉴욕', '증시', '욕증', '불안', '조에', '고조', '나스', '출발', '급락', '스닥', '하락', '투자']),
    ("e958", "뉴욕증시, 기술주 저가 매수에 혼조 출발", ['뉴욕', '증시', '욕증', '술주', '저가', '매수', '나스', '출발', '혼조', '스닥']),
    ("e959", "뉴욕증시, 엔비디아 반등에 나스닥 강세", ['뉴욕', '증시', '욕증', '엔비', '비디', '반등', '나스', '스닥', '강세', '디아']),
    ("e960", "뉴욕증시 기술주 랠리…나스닥 상승", ['뉴욕', '증시', '욕증', '술주', '랠리', '나스', '스닥', '상승']),
]
MARKET_WRAP = ("c700", "코스피·코스닥 동반 상승 마감…거래대금 늘어", ['코스', '스피', '스닥', '동반', '상승', '마감', '거래', '대금', '늘어'])


def _sections(briefs):
    from pipeline.edit import Placed
    host_ny, host_kq = Placed(_sc(*SPACEX, final=3), [], "economy"), Placed(_sc(*KOSDAQ, final=2), [], "economy")
    return {"economy": [host_ny, host_kq], "briefs": [Placed(_sc(*b, final=1 - k * 0.01), [], "briefs") for k, b in enumerate(briefs)]}, host_ny, host_kq


def test_related_overflow_not_moved_to_next_article():
    """뉴욕증시 기사에 관련 기사 3건이 찬 뒤 넷째 나스닥 기사가 다음 기사(코스닥 승강제)에 붙던 것 (S28d)."""
    from pipeline.edit import RELATED_MAX, attach_related
    sections, host_ny, host_kq = _sections(NY_BRIEFS)
    attach_related(sections)
    assert len(host_ny.related) == RELATED_MAX
    assert host_kq.related == []
    assert not sections["briefs"]          # 넘친 넷째는 단신에 되풀이하지도 않음 (S24c)


def test_related_ignores_common_fragments():
    """본 기사 둘이 같이 가진 "스닥" 을 빼면 "코스"·"거래" 두 조각만 공유하는 시황 단신은 코스닥 승강제 기사의 관련 기사가 아니다."""
    from pipeline.edit import attach_related, common_signature_tokens, related_score
    sections, host_ny, host_kq = _sections(NY_BRIEFS[:2] + [MARKET_WRAP])
    hosts = [host_ny.scored, host_kq.scored]
    wrap = sections["briefs"][-1].scored
    assert related_score(wrap, host_kq.scored) > 0                                  # 예전 판정: 스닥·코스·거래 3개 공유
    assert related_score(wrap, host_kq.scored, common_sig=common_signature_tokens(hosts)) == 0
    attach_related(sections)
    assert host_kq.related == []
    assert {p.scored.issue.id for p in host_ny.related} == {"e957", "e958"}
