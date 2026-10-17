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
    assert len(in_paper) == n
    reserves = [p for ps in ed.sections.values() for p in ps if p.reserve]
    assert len(reserves) == CFG.editing.reserve and all(p.section == "briefs" for p in reserves)
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
