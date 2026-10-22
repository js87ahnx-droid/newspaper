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
import re
from collections import Counter
from dataclasses import dataclass, field

from .collect import Article
from .textutil import clean_lead
from .score import CONTINUITY_MIN_SCORE, LATIN_ONLY_MIN, ScoredIssue, _LATIN, match_score
from .settings import COMPARE_TOPICS, Config, Interests

# 분야 → 섹션 (해당 섹션이 차면 단신으로)
TOPIC_SECTION = {
    "politics": "politics",
    "economy": "economy",
    "industry": "economy",
    "semis_ai": "economy",
    "international": "international",
    "society": "society",   # 사회·과학 면 (S21c — 전에는 자기 면이 없어 단신으로)
    "science": "society",
}
# 면별 최소 기사 수(S23a)를 지키는 뉴스 면
MIN_SECTIONS = ("politics", "economy", "international", "society", "interest")


def fits_section(s: ScoredIssue, sec: str, interest_topics: set[str]) -> bool:
    """이 기사가 그 뉴스 면에 갈 수 있나 (arrange 의 배정 규칙과 같게 — 반도체·AI 가 관심 분야면 관심면)."""
    semis_interest = s.topic == "semis_ai" and "semis_ai" in interest_topics
    if sec == "interest":
        return s.interest_hit or semis_interest
    return not semis_interest and TOPIC_SECTION.get(s.topic) == sec


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
    merged: list[ScoredIssue] = field(default_factory=list)  # 같은 사건 이웃 이슈 (따로 싣지 않고 이 기사에 합침)
    reserve: bool = False     # 예비 기사 — 쪽이 남을 때만 단신으로 실린다 (S15)
    filler: bool = False      # 면 최소 후보 (S23a) — 모자란 면을 채울 때만 쓰고, 안 쓰면 지면에 안 나간다
    related: list["Placed"] = field(default_factory=list)  # 관련 기사 (S22b) — 단신에서 옮겨 와 이 기사 아래에


@dataclass
class Edition:
    sections: dict[str, list[Placed]]
    compare: list[Placed]
    stats: dict = field(default_factory=dict)


def choose(scored: list[ScoredIssue], cfg: Config, interests: Interests) -> tuple[list[Placed], dict]:
    n = min(interests.daily_articles, len(scored))
    ed = cfg.editing
    placed: dict[str, Placed] = {}

    merged_into: dict[str, str] = {}

    def put(s: ScoredIssue, reason: str, guaranteed: bool = False):
        if s.issue.id in merged_into:
            return
        near = set(s.issue.extra.get("near", []))
        host = next((pid for pid in placed if pid in near), None)
        if host and s.issue.id not in placed:  # 같은 사건이 이미 실림 → 그 기사에 기사를 합친다 (슬롯은 다음 이슈에)
            placed[host].merged.append(s)
            merged_into[s.issue.id] = host
            return
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
    # S21c: '덜 보기' 분야(연예·스포츠·사건 등)는 빼고, 지면의 continuity_max_ratio 까지만 (점수 높은 순)
    less = set(interests.less)
    cont = [s for s in scored if s.days >= ed.continuity_min_days and s.topic not in less]
    for s in sorted(cont, key=lambda s: (-s.final, -s.days))[: math.floor(ed.continuity_max_ratio * n)]:
        put(s, f"연속 보도 {s.days}일째", guaranteed=True)

    # 4. 나머지: 최종 점수 순, 관심 상한
    remaining = n - len(placed)
    pool = [s for s in scored if s.issue.id not in placed and s.issue.id not in merged_into]
    if ed.interest_cap_mode == "driven":
        baseline = {s.issue.id for s in sorted(pool, key=lambda s: (-s.final_no_interest, s.issue.id))[:max(remaining, 0)]}
        is_interest = lambda s: s.issue.id not in baseline  # noqa: E731
    else:
        is_interest = lambda s: s.interest_hit  # noqa: E731
    cap = math.floor(ed.interest_cap * n)
    interest_count = sum(1 for p in placed.values() if ed.interest_cap_mode == "topic" and p.scored.interest_hit)
    skipped = 0
    # 분야별 상한 (S21c): 해외 매체가 많아 국제 이슈가 지면을 독점하지 않게 (10/18 미리보기: 국제 40/60, 넘친 16건이 단신)
    topic_cap = {t: math.floor(r * n) for t, r in ed.topic_max_ratio.items()}
    topic_count = Counter(p.scored.topic for p in placed.values())
    for s in sorted(pool, key=lambda s: (-s.final, s.issue.id)):
        if len(placed) >= n:
            break
        if s.topic in topic_cap and topic_count[s.topic] >= topic_cap[s.topic]:
            continue
        if is_interest(s):
            if interest_count >= cap:
                skipped += 1
                continue
            interest_count += 1
            put(s, "관심도 반영")
        else:
            put(s, "종합 점수")
        topic_count[s.topic] += 1
    # 예비: 하루 분량 다음 순위. 같은 사건 이웃이 이미 실렸으면 건너뛴다. 쪽이 남을 때만 한 줄 단신으로 실리므로
    # 관심 상한은 적용하지 않는다 (S21c — 관심 분야가 넓어 상한에 걸리면 예비가 16건뿐이었음)
    reserves: list[Placed] = []
    taken = set(placed) | set(merged_into)
    for s in sorted(scored, key=lambda s: (-s.final, s.issue.id)):
        if len(reserves) >= ed.reserve:
            break
        if s.issue.id in taken or set(s.issue.extra.get("near", [])) & taken:
            continue
        reserves.append(Placed(s, ["예비: 쪽이 남으면 단신"], reserve=True))
        taken.add(s.issue.id)
    # 면 최소 후보 (S23a): 면마다 그 면에 갈 다음 순위 기사를 몇 건씩 (예비에 없을 때 arrange 가 쓴다)
    fillers: list[Placed] = []
    if ed.section_min:
        interest_topics = {t for t, w in interests.topics.items() if w >= 1}
        rest = [s for s in sorted(scored, key=lambda s: (-s.final, s.issue.id)) if s.issue.id not in taken]
        for sec in MIN_SECTIONS:
            got = 0
            for s in rest:
                if got >= ed.section_min * 3:   # 같은 사건 이웃으로 몇 건 빠져도 되게 여유
                    break
                if s.issue.id in taken or not fits_section(s, sec, interest_topics):
                    continue
                fillers.append(Placed(s, [f"면 최소 후보: {sec}"], reserve=True, filler=True))
                taken.add(s.issue.id)
                got += 1
    stats = {
        "target": n,
        "reserve": len(reserves),
        "diversity_slots": len(diversity) + 1,
        "interest_counted": interest_count,
        "interest_cap": cap,
        "interest_skipped": skipped,
        "continuity_guaranteed": sum(1 for p in placed.values() if any(r.startswith("연속") for r in p.reasons)),
        "merged_duplicates": len(merged_into),
    }
    stats["section_fillers"] = len(fillers)
    return list(placed.values()) + reserves + fillers, stats


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
    reserves = sorted((p for p in placed if p.reserve and not p.filler), key=lambda p: (-p.scored.final, p.scored.issue.id))
    fillers = sorted((p for p in placed if p.filler), key=lambda p: (-p.scored.final, p.scored.issue.id))
    placed = [p for p in placed if not p.reserve]
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
        if sec and sec in caps and len(sections[sec]) < caps[sec]:
            p.section = sec
        elif (p.scored.interest_hit and "interest" in caps and len(sections["interest"]) < caps["interest"]
              and (p.scored.topic != "international"   # 관심면의 국제 기사는 절반까지 — 국제면과 겹치지 않게 (S21c)
                   or sum(q.scored.topic == "international" for q in sections["interest"]) < caps["interest"] // 2)):
            p.section = "interest"   # 자기 면이 다 찬 관심 분야 기사는 관심면으로 (S21c — 전에는 단신으로)
        else:
            p.section = "briefs"
        sections[p.section].append(p)

    # 면별 최소 (S23a): 모자란 뉴스 면은 그 면에 갈 기사 중 점수 높은 것으로 — 예비 기사 먼저, 없으면 면 최소 후보.
    # 1면으로 올라간 기사는 그 면 몫에 안 셈. 같은 사건이 이미 실린 후보는 건너뛴다. 채운 기사는 보장(넘침 정리에서 안 뺌)
    filled = 0
    want = cfg.editing.section_min
    if want:
        on_page = {q.scored.issue.id for q in placed} | {m.issue.id for q in placed for m in q.merged}
        for sec in MIN_SECTIONS:
            if sec not in caps:
                continue
            for src in (reserves, fillers):
                for p in list(src):
                    if len(sections[sec]) >= min(want, caps[sec]):
                        break
                    if not fits_section(p.scored, sec, interest_topics) or set(p.scored.issue.extra.get("near", [])) & on_page:
                        continue
                    src.remove(p)
                    p.reserve = p.filler = False
                    p.guaranteed = True
                    p.section = sec
                    p.reasons.append(f"면 최소 {want}건")
                    sections[sec].append(p)
                    placed.append(p)
                    on_page.add(p.scored.issue.id)
                    filled += 1

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
    for sid in ("politics", "economy", "international", "society", "interest"):
        for p in sections.get(sid, [])[: cfg.photos.per_section]:
            pick_photo(p, articles)

    for p in reserves:  # 단신 맨 뒤에 (지면 쪽이 남을 때만 보인다)
        p.section = "briefs"
        sections["briefs"].append(p)
    moved = attach_related(sections)
    stats = {
        "related_moved": moved,
        "section_min_filled": filled,
        "dropped_overflow": dropped,
        "photos": sum(1 for ps in sections.values() for p in ps if p.photo),
        "by_section": {**{k: len(v) for k, v in sections.items()}, "compare": len(compare)},
    }
    return Edition(sections=sections, compare=compare, stats=stats)


RELATED_MAX = 3          # 기사 하나에 붙이는 관련 기사 수
RELATED_HOSTS = ("front", "politics", "economy", "international", "society", "interest")


_TITLE_WORD = re.compile(r"[가-힣]{2,}|[a-z]{3,}|\d+")
_TITLE_TAG = re.compile(r"[\[\(（【][^\]\)）】]{0,12}[\]\)）】]")
TITLE_SAME = 0.5    # 짧은 쪽 제목 낱말의 이 비율 이상(2개 이상)을 공유하면 같은 기사로 본다 (S24c)
TITLE_COMMON = 3    # 그날 지면 제목 이만큼에 나온 낱말은 단서로 안 친다 ("부고 … 장모상", "premier league live")


def title_words(t: str) -> set[str]:
    return set(_TITLE_WORD.findall(_TITLE_TAG.sub(" ", t).lower()))


def same_title(a: str, b: str, common: set[str] | frozenset[str] = frozenset()) -> bool:
    """제목 낱말이 크게 겹치는가 — 다른 이슈로 갈라졌지만 같은 기사 (10/19호: KIA·LG 준PO 2연승 두 건,
    순직 소방관 딸의 손편지 두 건)."""
    ta, tb = title_words(a) - common, title_words(b) - common
    shared = ta & tb
    return len(shared) >= 2 and len(shared) >= TITLE_SAME * min(len(ta), len(tb))


def common_title_words(titles: list[str]) -> set[str]:
    df: dict[str, int] = {}
    for t in titles:
        for w in title_words(t):
            df[w] = df.get(w, 0) + 1
    return {w for w, c in df.items() if c >= TITLE_COMMON}


RELATED_HOST_SHARED = 2   # 본 기사 이만큼의 시그니처에 같이 나온 토큰은 어느 기사의 관련 기사인지 가리는 단서가 못 된다 (S28d)


def common_signature_tokens(hosts: list[ScoredIssue]) -> set[str]:
    """본 기사 여럿이 공유하는 시그니처 토큰 (S28d, 10/23호): 두 글자 조각이라 "뉴욕증시 … 나스닥" 기사와 "코스닥 승강제" 기사가
    "스닥" 을 공유해, 나스닥·코스닥 시황 단신이 승강제 기사의 관련 기사로 갈 수 있었다."""
    df: dict[str, int] = {}
    for s in hosts:
        for t in set(s.signature):
            df[t] = df.get(t, 0) + 1
    return {t for t, c in df.items() if c >= RELATED_HOST_SHARED}


def related_score(a: ScoredIssue, b: ScoredIssue, common: set[str] | frozenset[str] = frozenset(),
                  common_sig: set[str] | frozenset[str] = frozenset()) -> float:
    """두 이슈의 관련 정도 (S22b). 같은 사건 이웃(near)이나 같은 제목이면 확실, 아니면 연속성 판정과 같은 드문 토큰 공유 점수
    (본 기사 여럿이 공유하는 토큰 common_sig 은 빼고)."""
    if b.issue.id in a.issue.extra.get("near", []) or a.issue.id in b.issue.extra.get("near", []):
        return 99.0
    if same_title(a.issue.title, b.issue.title, common):
        return 98.0
    sa, sb = [t for t in a.signature if t not in common_sig], [t for t in b.signature if t not in common_sig]
    shared = set(sa) & set(sb)
    if not shared or (all(_LATIN.match(t) for t in shared) and len(shared) < LATIN_ONLY_MIN):
        return 0.0
    sc = match_score(sa, sb)
    return sc if sc >= CONTINUITY_MIN_SCORE else 0.0


def attach_related(sections: dict[str, list[Placed]], links: dict[str, str] | None = None) -> int:
    """단신(예비 포함) 중 앞 면 기사와 이어진 것을 그 기사 아래 '관련 기사'로 옮긴다 (S22b, 2026-10-18 사용자 요청).
    links(단신 이슈 id → 본 기사 이슈 id, AI 판정)가 있으면 그것을, 없으면 규칙(related_score)을 쓴다.
    점수 높은 단신부터, 가장 가까운 기사에, 기사당 RELATED_MAX 건까지. 옮긴 수를 돌려준다.
    이어진 기사가 이미 RELATED_MAX 건을 달았으면 그 단신은 지면에서 뺀다 — 앞에 나온 기사를 단신에 되풀이하지 않게 (S24c).
    가장 가까운 기사가 찼다고 덜 가까운 다른 기사에 넘겨 붙이지 않는다 (S28d — 10/23호 뉴욕증시 기사의 관련 기사가 다음 기사
    "코스닥 승강제" 에 붙었다)."""
    hosts = [p for sid in RELATED_HOSTS for p in sections.get(sid, [])]
    by_id = {h.scored.issue.id: h for h in hosts}
    common = common_title_words([p.scored.issue.title for ps in sections.values() for p in ps])
    common_sig = common_signature_tokens([h.scored for h in hosts])
    moved = 0
    for b in sorted(sections.get("briefs", []), key=lambda p: (p.reserve, -p.scored.final)):
        best, best_sc = None, 0.0
        if links is not None:
            best = by_id.get(links.get(b.scored.issue.id, ""))
        else:
            for h in hosts:
                sc = related_score(b.scored, h.scored, common, common_sig)
                if sc > best_sc:
                    best, best_sc = h, sc
        if best is None:
            continue
        sections["briefs"].remove(b)
        if len(best.related) < RELATED_MAX:
            best.related.append(b)
            b.section = best.section
            moved += 1
        else:
            b.section = ""
    return moved


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
        ids = list(dict.fromkeys(s.issue.article_ids + [i for m in p.merged for i in m.issue.article_ids]))
        arts = [articles[i] for i in ids]
        coverage = {**s.raw, "sources": len({a.source for a in arts}), "countries": len({a.country for a in arts})}
        return {
            "issue_id": s.issue.id,
            "title": s.issue.title,
            "lead": best_lead(rep, s.issue.article_ids),
            "url": rep.url,
            "source": rep.source,
            "lean": rep.lean,
            "topic": s.topic,
            "days": s.days,
            "asof": s.issue.extra.get("asof"),   # 시황 기사 시점 "뉴욕증시 22일(현지) 장중" (S28e)
            "timeline": s.timeline,
            "photo": p.photo,
            "photo_source": p.photo_source,
            "reasons": p.reasons,
            "reserve": p.reserve,
            "scores": {
                "attention": s.attention, "importance": s.importance, "continuity": s.continuity,
                "interest": s.interest, "final": s.final, "headline": s.headline, "frontline": s.frontline,
            },
            "headline_by": {**s.headline_by, **{k: v for m in p.merged for k, v in m.headline_by.items() if k not in s.headline_by}},
            "coverage": coverage,
            "merged": [m.issue.id for m in p.merged],
            "related": [item(r) for r in p.related],
            "articles": [
                {
                    "id": a.id, "source": a.source, "country": a.country, "lean": a.lean, "lang": a.lang,
                    "title": a.title, "lead": a.lead, "url": a.url, "paywall": a.paywall, "kind": a.kind,
                    "published": a.published,
                }
                for a in arts
            ],
        }

    return {
        "edition": edition_date,
        "sections": {sid: [item(p) for p in ps] for sid, ps in ed.sections.items()},
        "compare": [item(p) for p in ed.compare],
        "stats": {**choose_stats, **ed.stats},
    }
