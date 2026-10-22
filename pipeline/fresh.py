"""실릴 기사 최신성 검증 (S28f, 2026-10-23 "발행 때 실릴 기사들을 가장 최신 뉴스와 비교 검증해 지난 내용을 한 번 더 거르기").

1. 지면에 실린 기사마다 같은 이야기를 1시간 넘게 늦게 다룬 이슈(같은 사건 이웃·같은 제목·드문 토큰 공유)를 찾는다 — 규칙
2. AI 가 쌍마다 "새 보도 때문에 지면 기사가 이미 지난 소식이 됐나" 판정 — 하루 1번 호출(쌍 MAX_PAIRS 까지)
3. 지난 기사는 빼고, 그 새 보도가 자리를 이어받도록 점수를 넘긴 뒤 다시 편집한다 (호출부)
AI 가 없거나 실패하면 아무것도 빼지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .edit import RELATED_HOSTS, related_score, title_words

MAX_PAIRS = 80
PER_ITEM = 2
NEWER_BY = timedelta(hours=1)
CHECK_SECTIONS = (*RELATED_HOSTS, "briefs")

PROMPT = """아래 각 쌍(P번호)에서 "지면"은 오늘 아침 신문에 실릴 기사, "새 보도"는 같은 이야기를 그보다 늦게 다룬 보도다. 시각은 한국 시간.
새 보도 때문에 지면 기사가 이미 지난 소식이 되었으면 고른다:
- 결과·수치가 바뀜 (협상 중 → 타결·결렬, 사망 10명 → 30명, 잠정 → 확정)
- 장중·예상·전망이 마감·결과로 나옴 (증시 장중 → 마감, 표결 앞둠 → 가결)
- 상황이 뒤집힘 (부인 → 시인, 발표 → 철회)
- 같은 내용을 더 새 정보로 다시 쓴 판
같은 이야기라도 지면 기사가 다른 측면(배경·반응·분석)을 다뤄 여전히 의미가 있으면 고르지 않는다. 애매하면 고르지 않는다.
출력 형식: {{"stale": ["P0", ...]}}
{data}"""


def newest_time(s, articles: dict) -> datetime | None:
    ts = [articles[i].published for i in s.issue.article_ids if i in articles and articles[i].published]
    return datetime.fromisoformat(max(ts)) if ts else None


def find_pairs(sections: dict, scored: list, articles: dict) -> list[tuple]:
    """(지면 기사 Placed, 더 새 이슈 ScoredIssue) 쌍. 점수 높은 지면 기사부터, 기사당 PER_ITEM, 모두 MAX_PAIRS 까지."""
    placed = [p for sid in CHECK_SECTIONS for p in sections.get(sid, [])]
    when = {s.issue.id: newest_time(s, articles) for s in scored}
    # 관련 기사(S28d)와 달리 지면 기사 여럿이 공유하는 토큰도 쓴다 — 같은 이야기의 앞선 판이 지면에 같이 있는 경우가 바로 거를 대상.
    # 두 글자 조각이 우연히 겹친 쌍은 AI 가 거른다
    toks = {s.issue.id: set(s.signature) | title_words(s.issue.title) for s in scored}
    pairs = []
    for p in sorted(placed, key=lambda p: -p.scored.final):
        t0 = when.get(p.scored.issue.id) or newest_time(p.scored, articles)
        if t0 is None:
            continue
        cand = []
        for s in scored:
            t = when[s.issue.id]   # 지면에 이미 실린 더 새 이슈도 비교 대상 (같은 이야기의 앞선 판을 뺀다)
            if s.issue.id == p.scored.issue.id or t is None or t < t0 + NEWER_BY:
                continue
            near = s.issue.id in p.scored.issue.extra.get("near", []) or p.scored.issue.id in s.issue.extra.get("near", [])
            mine = toks.get(p.scored.issue.id) or set(p.scored.signature) | title_words(p.scored.issue.title)
            if not near and not (toks[s.issue.id] & mine):
                continue   # 빠른 거름: 같은 사건 이웃도 아니고 토큰·낱말도 안 겹침
            sc = related_score(p.scored, s)
            if sc > 0:
                cand.append((sc, t, s))
        cand.sort(key=lambda c: (-c[0], -c[1].timestamp()))
        for _, _, s in cand[:PER_ITEM]:
            pairs.append((p, s))
            if len(pairs) >= MAX_PAIRS:
                return pairs
    return pairs


def _title(s, articles: dict) -> str:
    """한국어·영어 제목 먼저."""
    arts = sorted((articles[i] for i in s.issue.article_ids if i in articles), key=lambda a: (a.lang != "ko", a.lang != "en"))
    rep = articles.get(s.issue.rep_article)
    return (rep.title if rep and rep.lang in ("ko", "en") else arts[0].title if arts else s.issue.title)[:100]


def ai_stale(pairs: list[tuple], articles: dict, ask, tz: str = "Asia/Seoul") -> tuple[set[int], str]:
    """AI 판정: 지난 소식이 된 쌍 번호들, 상태."""
    if not pairs:
        return set(), "후보 없음"
    z = ZoneInfo(tz)

    def hm(s):
        t = newest_time(s, articles)
        return t.astimezone(z).strftime("%m/%d %H:%M") if t else "?"
    lines = [f"P{i}\t지면 [{hm(p.scored)}] {_title(p.scored, articles)}\n\t새 보도 [{hm(s)}] {_title(s, articles)}"
             for i, (p, s) in enumerate(pairs)]
    res = ask(PROMPT.format(data="<data>\n" + "\n".join(lines) + "\n</data>"))
    got = res.get("stale") if isinstance(res, dict) else None
    if not isinstance(got, list):
        return set(), "응답 없음"
    out = set()
    for k in got:
        try:
            i = int(str(k).strip().lstrip("Pp"))
        except ValueError:
            continue
        if 0 <= i < len(pairs):
            out.add(i)
    return out, f"{len(pairs)}쌍 → 지난 기사 {len({pairs[i][0].scored.issue.id for i in out})}건"


def drop_and_promote(scored: list, pairs: list[tuple], stale: set[int]) -> tuple[list, list[str]]:
    """지난 기사를 빼고, 새 보도에 그 기사 점수를 넘긴다(다시 편집하면 그 자리를 잇게). 돌려주는 값: (이슈 목록, 기록)."""
    gone, notes = set(), []
    for i in sorted(stale):
        p, s = pairs[i]
        old = p.scored
        if old.issue.id in gone:
            continue
        gone.add(old.issue.id)
        s.final, s.frontline = max(s.final, old.final), max(s.frontline, old.frontline)
        s.final_no_interest = max(s.final_no_interest, old.final_no_interest)
        s.topic = old.topic   # 같은 이야기 — 앞 기사의 면을 잇는다
        notes.append(f"{old.issue.title[:40]} → {s.issue.title[:40]}")
    return [s for s in scored if s.issue.id not in gone], notes
