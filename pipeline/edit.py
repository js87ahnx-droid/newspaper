"""5단계 편집: 어떤 이슈를 실을지 고르고, 지면(섹션)에 배치하고, 사진 자리를 정한다.

고르는 순서 (지시서 5-3):
1. 1면 톱 — 주목도·중요도만으로 (관심도 미반영)
2. 다양성 슬롯 — 전체의 diversity_ratio 만큼, 관심도와 무관하게 주목도 상위
3. 연속 이슈 — continuity_min_days 이상 이어진 이슈는 최소 단신으로
4. 나머지 — 최종 점수 순. 단 "관심도 덕분에 들어온 기사"는 interest_cap 이하
   (interest_cap_mode=driven: 관심도를 뺀 점수로 골랐다면 빠졌을 기사 / topic: 관심 분야 기사 전체)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .collect import Article
from .textutil import clean_lead
from .score import ScoredIssue
from .settings import COMPARE_TOPICS, Config, Interests

# 분야 → 섹션 (해당 섹션이 차면 단신으로)
TOPIC_SECTION = {
    "politics": "politics",
    "economy": "economy",
    "industry": "economy",
    "semis_ai": "economy",
    "international": "international",
}
# 입장 비교 유형 → 분야
COMPARE_TOPIC_MAP = {
    "diplomacy_security": {"politics", "international"},
    "economic_policy": {"economy"},
    "domestic_politics": {"politics"},
    "tech_regulation": {"semis_ai"},
}


@dataclass
class Placed:
    scored: ScoredIssue
    reasons: list[str]
    section: str = ""
    photo: str | None = None
    photo_source: str | None = None
    guaranteed: bool = False  # 다양성·연속성으로 들어온 기사 — 넘침 정리 때 빼지 않는다


@dataclass
class Edition:
    sections: dict[str, list[Placed]]
    compare: list[Placed]
    stats: dict = field(default_factory=dict)


def choose(scored: list[ScoredIssue], cfg: Config, interests: Interests) -> tuple[list[Placed], dict]:
    n = min(interests.daily_articles, len(scored))
    ed = cfg.editing
    placed: dict[str, Placed] = {}

    def put(s: ScoredIssue, reason: str, guaranteed: bool = False):
        p = placed.get(s.issue.id)
        if p:
            if reason not in p.reasons:
                p.reasons.append(reason)
            p.guaranteed = p.guaranteed or guaranteed
        else:
            placed[s.issue.id] = Placed(s, [reason], guaranteed=guaranteed)

    # 1. 1면 톱
    by_front = sorted(scored, key=lambda s: (-s.frontline, -s.attention, s.issue.id))
    top = by_front[0]
    put(top, "1면 톱: 주목도·중요도 1위", guaranteed=True)

    # 2. 다양성 슬롯
    d = math.ceil(ed.diversity_ratio * n)
    by_att = sorted(scored, key=lambda s: (-s.attention, -s.importance, s.issue.id))
    diversity = [s for s in by_att if s.issue.id != top.issue.id][: max(d - 1, 0)]
    for s in diversity:
        put(s, "다양성: 주목도 상위", guaranteed=True)

    # 3. 연속 이슈
    for s in sorted(scored, key=lambda s: (-s.days, -s.final)):
        if s.days >= ed.continuity_min_days:
            put(s, f"연속 보도 {s.days}일째", guaranteed=True)

    # 4. 나머지: 최종 점수 순, 관심 상한
    remaining = n - len(placed)
    pool = [s for s in scored if s.issue.id not in placed]
    if ed.interest_cap_mode == "driven":
        baseline = {s.issue.id for s in sorted(pool, key=lambda s: (-s.final_no_interest, s.issue.id))[:max(remaining, 0)]}
        is_interest = lambda s: s.issue.id not in baseline  # noqa: E731
    else:
        is_interest = lambda s: s.interest_hit  # noqa: E731
    cap = math.floor(ed.interest_cap * n)
    interest_count = sum(1 for p in placed.values() if ed.interest_cap_mode == "topic" and p.scored.interest_hit)
    skipped = 0
    for s in sorted(pool, key=lambda s: (-s.final, s.issue.id)):
        if len(placed) >= n:
            break
        if is_interest(s):
            if interest_count >= cap:
                skipped += 1
                continue
            interest_count += 1
            put(s, "관심도 반영")
        else:
            put(s, "종합 점수")
    stats = {
        "target": n,
        "diversity_slots": len(diversity) + 1,
        "interest_counted": interest_count,
        "interest_cap": cap,
        "interest_skipped": skipped,
        "continuity_guaranteed": sum(1 for p in placed.values() if any(r.startswith("연속") for r in p.reasons)),
    }
    return list(placed.values()), stats


def pick_photo(p: Placed, articles: dict[str, Article]) -> None:
    """대표 기사 이미지 우선, 없으면 같은 이슈의 다른 기사 중 영향력 높은 매체의 이미지."""
    rep = articles[p.scored.issue.rep_article]
    if rep.image:
        p.photo, p.photo_source = rep.image, rep.source
        return
    others = sorted((articles[i] for i in p.scored.issue.article_ids), key=lambda a: -a.weight)
    for a in others:
        if a.image:
            p.photo, p.photo_source = a.image, a.source
            return


def arrange(placed: list[Placed], cfg: Config, interests: Interests, articles: dict[str, Article]) -> Edition:
    caps = {s.id: s.max_articles for s in cfg.sections}
    sections: dict[str, list[Placed]] = {s.id: [] for s in cfg.sections}
    order = sorted(placed, key=lambda p: (-p.scored.final, p.scored.issue.id))

    # 1면: 톱 + 주목도·중요도 상위
    top = next(p for p in placed if any(r.startswith("1면 톱") for r in p.reasons))
    sections["front"].append(top)
    rest_front = sorted((p for p in placed if p is not top), key=lambda p: (-p.scored.frontline, p.scored.issue.id))
    for p in rest_front[: caps["front"] - 1]:
        sections["front"].append(p)
    for p in sections["front"]:
        p.section = "front"

    interest_topics = {t for t, w in interests.topics.items() if w >= 1}
    for p in order:
        if p.section:
            continue
        sec = TOPIC_SECTION.get(p.scored.topic)
        # 관심 섹션: 관심 키워드가 나온 기사, 또는 경제 섹션에 들어갈 반도체·AI 기사(관심 분야일 때)
        kw_hit = p.scored.interest_hit and p.scored.topic not in interest_topics
        if p.scored.topic == "semis_ai" and "semis_ai" in interest_topics:
            sec = "interest"
        elif kw_hit or ("관심도 반영" in p.reasons and sec is None):
            sec = "interest"
        if sec and len(sections[sec]) < caps[sec]:
            p.section = sec
        else:
            p.section = "briefs"
        sections[p.section].append(p)

    # 단신은 다른 면에서 넘친 기사를 받는 면이다. 전체가 하루 분량(target)을 넘지 않으면 상한을 넘어도 받고,
    # 넘을 때만 보장되지 않은 기사부터 점수 낮은 순으로 뺀다
    target = len(placed)
    others = sum(len(v) for k, v in sections.items() if k != "briefs")
    briefs_cap = max(caps["briefs"], target - others)
    dropped = 0
    while len(sections["briefs"]) > briefs_cap:
        removable = [p for p in sections["briefs"] if not p.guaranteed]
        if not removable:
            break
        worst = min(removable, key=lambda p: p.scored.final)
        sections["briefs"].remove(worst)
        worst.section = ""
        dropped += 1

    # 입장 비교: 성향이 둘 이상 갈리거나 국가가 둘 이상인 이슈 (선호 유형 먼저, 그다음 주목도)
    want = set().union(*(COMPARE_TOPIC_MAP[c] for c in interests.compare_topics if c in COMPARE_TOPICS)) if interests.compare_topics else set()
    cands = [
        p for p in placed
        if p.section and (len(set(p.scored.issue.leans)) >= 2 or len(p.scored.issue.countries) >= 2)
        and len(p.scored.issue.sources) >= 3
    ]
    cands.sort(key=lambda p: (p.scored.topic not in want, -p.scored.attention, p.scored.issue.id))
    compare = cands[: caps["compare"]]

    for sid in sections:
        if sid != "front":
            sections[sid].sort(key=lambda p: (-p.scored.final, p.scored.issue.id))

    # 사진: 1면(상한 photos.front, 톱부터 차례로), 섹션 머리기사(photos.per_section) — 정해진 자리에
    # 이미지가 있을 때만 붙인다. 사진 때문에 순위를 바꾸지 않는다
    for p in placed:
        p.photo = p.photo_source = None
    photos_front = 0
    for p in sections["front"]:
        if photos_front >= cfg.photos.front:
            break
        pick_photo(p, articles)
        photos_front += bool(p.photo)
    for sid in ("politics", "economy", "international", "interest"):
        for p in sections[sid][: cfg.photos.per_section]:
            pick_photo(p, articles)

    stats = {
        "dropped_overflow": dropped,
        "photos": sum(1 for ps in sections.values() for p in ps if p.photo),
        "by_section": {**{k: len(v) for k, v in sections.items()}, "compare": len(compare)},
    }
    return Edition(sections=sections, compare=compare, stats=stats)


def edition_to_json(ed: Edition, edition_date: str, articles: dict[str, Article], choose_stats: dict) -> dict:
    """지면 생성(S8)이 읽을 데이터. 기사 본문은 없다(제목·RSS 리드·링크·이미지 주소만)."""

    def best_lead(rep: Article, issue_ids: list[str]) -> str:
        """대표 기사 리드가 비었거나 부실하면 같은 언어의 다른 기사 리드 중 가장 충실한 것 (같은 사건이므로)."""
        own = clean_lead(rep.lead)
        if own:
            return own
        others = [clean_lead(articles[i].lead) for i in issue_ids if articles[i].lang == rep.lang]
        return max(others, key=len, default="")

    def item(p: Placed) -> dict:
        s = p.scored
        rep = articles[s.issue.rep_article]
        return {
            "issue_id": s.issue.id,
            "title": s.issue.title,
            "lead": best_lead(rep, s.issue.article_ids),
            "url": rep.url,
            "source": rep.source,
            "lean": rep.lean,
            "topic": s.topic,
            "days": s.days,
            "timeline": s.timeline,
            "photo": p.photo,
            "photo_source": p.photo_source,
            "reasons": p.reasons,
            "scores": {
                "attention": s.attention, "importance": s.importance, "continuity": s.continuity,
                "interest": s.interest, "final": s.final,
            },
            "coverage": s.raw,
            "articles": [
                {
                    "id": a.id, "source": a.source, "country": a.country, "lean": a.lean, "lang": a.lang,
                    "title": a.title, "lead": a.lead, "url": a.url, "paywall": a.paywall, "kind": a.kind,
                }
                for a in (articles[i] for i in s.issue.article_ids)
            ],
        }

    return {
        "edition": edition_date,
        "sections": {sid: [item(p) for p in ps] for sid, ps in ed.sections.items()},
        "compare": [item(p) for p in ed.compare],
        "stats": {**choose_stats, **ed.stats},
    }
