"""4단계 점수: 주목도·중요도·연속성·관심도 (각 0~1) 와 최종 점수.

- 주목도: 다룬 매체들의 영향력 가중치 합 + 다룬 국가 수 + 매체 메인 피드 노출 수 (그날 최댓값으로 나눔)
- 중요도: 분야 기본 가중치 + 핵심 키워드 가산 + 다룬 국가 수 (그날 최댓값으로 나눔)
- 연속성: data/history 의 전날 이슈와 이어지면 "○일째 보도". 7일째에 1.0
- 관심도: interests.yaml 의 분야 가중치 + 관심 키워드 가산 (가능한 최댓값으로 나눔)
- 머리기사(S14b): 이 이슈를 그날 머리기사(종이신문 1면·홈페이지 맨 위)로 올린 매체들의 가중치 × 순위 가중 합 (그날 최댓값으로 나눔).
  최종 점수(weights.headline)와 1면 선정(weights.front_headline, 주목도·중요도와 함께)에 쓴다
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .cluster import Issue
from .collect import Article
from .interest import InterestTable
from .lexical import tokens
from .settings import Config
from .topics import classify


@dataclass
class ScoredIssue:
    issue: Issue
    topic: str
    attention: float
    importance: float
    continuity: float
    interest: float
    final: float
    frontline: float             # 1면 톱 선정용 (주목도·중요도만)
    final_no_interest: float     # 관심도를 뺀 최종 점수 (관심 상한 판정용)
    days: int                    # ○일째 보도
    interest_hit: bool           # 관심 분야(가중치 ≥ 1)이거나 관심 키워드가 나옴
    signature: list[str] = field(default_factory=list)  # 다음날 연속성 비교용 토큰
    raw: dict = field(default_factory=dict)
    timeline: list[dict] = field(default_factory=list)
    headline: float = 0.0              # 머리기사 점수 (0~1)
    headline_by: dict = field(default_factory=dict)  # 매체 → [순위, 얻은 곳] (1면·머리기사로 올린 곳)  # 지난 경과: 앞선 호들의 {date, title, summary} (오래된 것부터)


SIGNATURE_SIZE = 12
_HANGUL_1 = re.compile(r"[가-힣]")  # 한 글자 한글 토큰은 뜻이 약하다
DISTINCT_DF_RATIO = 0.01   # 그날 기사의 1% 이하에만 나온 토큰을 "드문" 토큰으로 본다
CONTINUITY_MIN_SCORE = 3.0  # 전날 이슈와 공유한 드문 토큰 점수가 이 이상이면 같은 이슈가 이어진 것으로 본다
# 점수: 한글 2글자 조각 1, 영문 단어 1.5 (한 단어가 여러 조각으로 쪼개지지 않으므로),
#       성씨로 시작하는 세 글자 이름(앞뒤 조각 둘 다 공유) +1. 10/15→10/16 실측에서 문턱 2 는 "미사일"·"또다시"
#       같은 낱말 하나로 엉뚱한 이슈가 이어졌고, 3 + 이 가중치로는 틀린 연결이 없었다.
SURNAMES = set("김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예봉경")
_LATIN = re.compile(r"[a-z]")


def title_df(articles: list[Article]) -> dict[str, int]:
    """그날 전체 기사 제목에서 각 토큰이 나온 기사 수."""
    df: dict[str, int] = {}
    for a in articles:
        for t in set(tokens(a.title)):
            df[t] = df.get(t, 0) + 1
    return df


def issue_signature(arts: list[Article], df: dict[str, int], n_docs: int, limit: int = SIGNATURE_SIZE) -> list[str]:
    """이슈를 다른 날과 이어 볼 때 쓰는 "드문" 토큰들: 이슈 안에서 자주, 그날 전체에서는 드물게 나온 토큰.
    인명·지명·고유명사가 주로 남는다. (공개 history 에 저장되므로 제목에서만 뽑는다 — 본문·리드 없음)"""
    counts: dict[str, int] = {}
    for a in arts:
        for t in set(tokens(a.title)):
            counts[t] = counts.get(t, 0) + 1
    max_df = max(3, int(n_docs * DISTINCT_DF_RATIO))
    # 드문지 여부는 이 이슈 자기 기사를 빼고 센다 (크게 보도된 이슈일수록 핵심어가 여러 기사에 나오므로)
    outside = {t: df.get(t, 0) - c for t, c in counts.items()}
    cands = [
        t for t in counts
        if outside[t] <= max_df and not _HANGUL_1.fullmatch(t) and not t.startswith(("@", "#"))  # 단서 토큰은 일반 토큰과 중복
    ]
    ranked = sorted(cands, key=lambda t: (-counts[t] * math.log((n_docs + 1) / (outside[t] + 1)), t))
    return ranked[:limit]


# 머리기사 점수 = 1 - exp(-합/HEADLINE_SCALE): 매체가 늘수록 포화. 그날 최댓값으로 나누면 압도적인 이슈 하나(10/16 코스피,
# 신문 5곳 1면) 때문에 다른 1면 기사(청해부대 — 경향 1면 머리·조선 1면)가 0.4 로 눌려 1면에서 빠졌다.
# 이 식으로는 한 곳 1면 머리 0.49, 두 곳 0.74, 다섯 곳(순위 섞임) 0.85~0.9
HEADLINE_SCALE = 1.5

TIMELINE_MAX = 7  # 지난 경과로 들고 다니는 앞선 호 수


def load_previous(history_dir: Path, edition: date, lookback: int = 3) -> tuple[date | None, list[dict]]:
    """가장 가까운 이전 호의 history (발행을 빠뜨린 날이 있어도 이어지도록 시간창 최대 길이만큼 본다)."""
    for back in range(1, lookback + 1):
        d = edition - timedelta(days=back)
        p = history_dir / f"{d.isoformat()}.json"
        if p.exists():
            return d, json.loads(p.read_text(encoding="utf-8"))["issues"]
    return None, []


def match_score(a: list[str], b: list[str]) -> float:
    shared = set(a) & set(b)
    score = sum(1.5 if _LATIN.match(t) else 1.0 for t in shared)
    for t in shared:  # 성씨+두 글자 이름: "김지"·"지용" 을 함께 공유
        if len(t) == 2 and t[0] in SURNAMES and any(u != t and len(u) == 2 and u[0] == t[1] for u in shared):
            score += 1.0
            break
    return score


LATIN_ONLY_MIN = 3  # 공유 토큰이 모두 영어 낱말이면 3개 이상 (10/16 실측: "north korea"·"attack ship"·"record soar"
                    # 두 낱말로 다른 사건이 이어졌다 — 지난 경과로 지면에 드러나므로 놓치는 쪽을 택한다)


def continuity_match(sig: list[str], previous: list[dict]) -> dict | None:
    best = None
    for prev in previous:
        shared = set(sig) & set(prev["signature"])
        if shared and all(_LATIN.match(t) for t in shared) and len(shared) < LATIN_ONLY_MIN:
            continue
        sc = match_score(sig, prev["signature"])
        if sc >= CONTINUITY_MIN_SCORE and (best is None or (sc, prev["days"]) > best[0]):
            best = ((sc, prev["days"]), prev)
    return best[1] if best else None


def continuity_days(sig: list[str], previous: list[dict]) -> int:
    m = continuity_match(sig, previous)
    return 1 + m["days"] if m else 1


def past_timeline(prev: dict | None) -> list[dict]:
    """이어진 앞선 이슈의 경과 (그 이슈 자신 포함). 예전 기록에 timeline 이 없으면 제목만으로 한 줄."""
    if not prev:
        return []
    tl = prev.get("timeline") or [{"date": prev.get("date"), "title": prev["title"], "summary": prev.get("summary")}]
    return tl[-TIMELINE_MAX:]


def score_issues(
    issues: list[Issue],
    articles: dict[str, Article],
    cfg: Config,
    table: InterestTable,
    previous: list[dict],
    headlines: list[dict] | None = None,
) -> list[ScoredIssue]:
    from .headlines import RANK_WEIGHT, group_members, issue_headlines

    # 같은 기사거리 묶음에 든 이슈끼리는 같은 사건 이웃(near)으로 — 편집에서 한 기사로 합친다
    owner = {a: iss.id for iss in issues for a in iss.article_ids}
    for members in group_members(headlines or []):
        ids = sorted({owner[a] for a in members if a in owner})
        for iss in issues:
            if iss.id in ids:
                near = iss.extra.setdefault("near", [])
                near += [x for x in ids if x != iss.id and x not in near]

    imp_cfg = cfg.importance
    kw = [re.compile(re.escape(k), re.I) for k in imp_cfg.keywords]
    rows = []
    all_arts = [articles[i] for iss in issues for i in iss.article_ids]
    df = title_df(all_arts)
    for iss in issues:
        arts = [articles[i] for i in iss.article_ids]
        topic = classify(arts)
        by_source: dict[str, Article] = {}
        for a in arts:
            by_source.setdefault(a.source, a)
        countries = len({a.country for a in arts})
        mains = len({a.source for a in arts if a.main})
        att_raw = sum(a.weight for a in by_source.values()) + 0.5 * (countries - 1) + 0.3 * mains
        titles = " ".join(a.title for a in arts)
        kw_hits = sum(1 for p in kw if p.search(titles))
        imp_raw = imp_cfg.topic_weights[topic] + imp_cfg.keyword_bonus * min(kw_hits, 3) + 0.1 * min(countries - 1, 3)
        int_raw = table.score(topic, titles)
        sig = issue_signature(arts, df, len(all_arts))
        hl_by = issue_headlines(headlines or [], iss.article_ids)
        hl_raw = sum(RANK_WEIGHT.get(r, 0) * by_source.get(src, articles[iss.article_ids[0]]).weight
                     for src, (r, _) in hl_by.items())
        prev = continuity_match(sig, previous)
        days = 1 + prev["days"] if prev else 1
        hit = table.topic_weights.get(topic, 0) >= 1 or any(k.lower() in titles.lower() for k in table.keywords)
        rows.append((iss, topic, att_raw, imp_raw, int_raw, days, hit, sig,
                     {"sources": len(by_source), "countries": countries, "main_sources": mains, "keyword_hits": kw_hits},
                     past_timeline(prev), hl_raw, hl_by))

    max_att = max((r[2] for r in rows), default=1) or 1
    max_imp = max((r[3] for r in rows), default=1) or 1
    max_int = (max(table.topic_weights.values(), default=1) + table.keyword_boost) or 1
    w = cfg.weights
    wsum = w.attention + w.importance + w.continuity + w.interest + w.headline
    front_wsum = (w.attention + w.importance + w.front_headline) or 1
    out = []
    for iss, topic, a, i, it, days, hit, sig, raw, tl, hl, hl_by in rows:
        att, imp, inte = a / max_att, i / max_imp, min(it / max_int, 1.0)
        cont = min(days - 1, 6) / 6
        head = 1 - math.exp(-hl / HEADLINE_SCALE)
        base = w.attention * att + w.importance * imp + w.continuity * cont + w.headline * head
        out.append(
            ScoredIssue(
                issue=iss, topic=topic,
                attention=round(att, 4), importance=round(imp, 4), continuity=round(cont, 4), interest=round(inte, 4),
                final=round((base + w.interest * inte) / wsum, 4),
                frontline=round((w.attention * att + w.importance * imp + w.front_headline * head) / front_wsum, 4),
                final_no_interest=round(base / ((wsum - w.interest) or 1), 4),
                days=days, interest_hit=hit, signature=sig, raw=raw, timeline=tl,
                headline=round(head, 4), headline_by=hl_by,
            )
        )
    return out


def write_history(history_dir: Path, edition: date, scored: list[ScoredIssue], placed_ids: set[str]) -> Path:
    """연속성 계산용 기록. 지면에 실린 이슈 + 2개 매체 이상이 다룬 이슈 (지면에 안 실려도 "보도는 이어짐").
    제목·분야·토큰·일수·지난 경과만 저장 — 본문·리드·임베딩 없음 (공개 저장소).
    경과의 summary 는 LLM 이 쓴 이슈 정리(enrich 가 채움) — 기사 문장이 아니다."""
    keep = [s for s in scored if s.issue.id in placed_ids or len(s.issue.sources) >= 2]
    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_dir / f"{edition.isoformat()}.json"
    data = {
        "edition": edition.isoformat(),
        "issues": [
            {"id": s.issue.id, "title": s.issue.title, "topic": s.topic, "days": s.days, "signature": s.signature,
             "date": edition.isoformat(),
             "timeline": (s.timeline + [{"date": edition.isoformat(), "title": s.issue.title, "summary": None}])[-TIMELINE_MAX:]}
            for s in keep
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def scored_to_json(s: ScoredIssue) -> dict:
    d = asdict(s)
    d["issue"] = asdict(s.issue)
    return d
