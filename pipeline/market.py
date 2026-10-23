"""증시 기사 시점 판정 (S28e, 2026-10-23 사용자 요청).

10/23호에 21일(현지) 뉴욕증시 마감 기사와 22일 장중 기사가 실렸다 — 22일 마감이 있어야 할 때.
시간창 마감(05:30 KST)이 뉴욕 장 마감(서머타임 05:00, 아니면 06:00 KST) 직후라, 마감 기사((종합) 06~07시)는
늘 다음 날 호 시간창에 들어가 하루 묵은 채 "오늘 소식"처럼 실렸다.

- 시황 기사(제목: 시장 이름 + 등락·마감·출발 등)를 골라, 기사 시각으로 어느 거래일의 장중·마감·개장 전 소식인지 정한다
  (뉴욕은 America/New_York — 서머타임 반영, 한국은 KST)
- 발행 기준 시각 T 에 이미 끝난 가장 최근 거래일 L 보다 앞선 거래일 소식은 지면에서 뺀다
- 같은 시장의 더 새 시점 소식(같은 거래일 마감 > 장중 > 개장 전, 더 뒤 거래일)이 있으면 앞선 것을 뺀다
- 남는 시황 기사에는 시점("뉴욕증시 22일(현지) 장중")을 붙인다 — 지난 장중 소식이 지금 마감처럼 보이지 않게
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY, SEOUL = ZoneInfo("America/New_York"), ZoneInfo("Asia/Seoul")

# 휴장일 (주말 말고). 모르는 해는 주말만 쉰다고 본다 — 틀려도 "앞 거래일 마감"으로 보아 지면에 남는 쪽으로 어긋난다
US_HOLIDAYS = {date.fromisoformat(d) for d in (
    "2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03 2026-09-07 2026-11-26 2026-12-25 "
    "2027-01-01 2027-01-18 2027-02-15 2027-03-26 2027-05-31 2027-06-18 2027-07-05 2027-09-06 2027-11-25 2027-12-24").split()}
KR_HOLIDAYS = {date.fromisoformat(d) for d in (
    "2026-01-01 2026-02-16 2026-02-17 2026-02-18 2026-03-02 2026-05-01 2026-05-05 2026-05-25 2026-06-03 2026-08-17 "
    "2026-09-24 2026-09-25 2026-10-05 2026-10-09 2026-12-25 2026-12-31").split()}


@dataclass(frozen=True)
class Market:
    id: str
    tz: ZoneInfo
    open: time
    close: time
    holidays: frozenset
    local: str   # 날짜 뒤에 붙임: 뉴욕은 "(현지)"


MARKETS = {
    "us": Market("us", NY, time(9, 30), time(16, 0), frozenset(US_HOLIDAYS), "(현지)"),
    "kr": Market("kr", SEOUL, time(9, 0), time(15, 30), frozenset(KR_HOLIDAYS), ""),
}

_US = re.compile(r"뉴욕\s?증시|뉴욕증권|나스닥|다우\s?지수|다우존스|\bS&P\s?500|S&P|월가|월스트리트|wall street|nasdaq|dow jones|the dow\b|u\.?s\.? stocks", re.I)
_KR = re.compile(r"코스피|코스닥|kospi|kosdaq|국내\s?증시|서울\s?증시", re.I)
_MOVE = re.compile(
    r"상승|하락|강세|약세|반등|반락|급락|급등|폭락|폭등|혼조|마감|출발|보합|↑|↓|\d\s?%|올라|내려|떨어|밀려|뛰어|최고치|최저치|랠리|"
    r"\b(rall|fall|fell|rise|rose|slid|slip|jump|gain|drop|clos|end|tumbl|surg|sink|sank|climb|slump|rebound|record|higher|lower|open)", re.I)
# 한 거래일 시황이 아닌 것: 주간·월간·전망 해설, 제도(승강제·상장), 물음표로 끝나는 해설,
# 종목 기사("[특징주]", "삼성전기, 코스피 약세에도 4% 상승", 공모주 입성)
_NOT_SESSION = re.compile(r"주간|주\s?새|주째|이번\s?주|한\s?주|한\s?달|개월|올해|연초|상반기|하반기|전망|승강|상장|ETF|"
                          r"특징주|(약세|강세|하락|상승|급락|급등|부진)에도|입성|공모가|"
                          r"\bweek|\bmonth|\byear|outlook|\?\s*$|？\s*$", re.I)
_PRE = re.compile(r"선물|개장\s?전|프리마켓|개장\s?앞|\bfutures\b|pre-?market", re.I)
_INTRA = re.compile(r"출발|장중|오전장|오후장|개장\s?초|\bopens?\b|\bmidday\b|\bintraday\b|early trad|morning trad", re.I)
_CLOSE = re.compile(r"마감|장 마쳐|\bclos(e|es|ed|ing)\b|\bends?\b|\bfinish|\bsettle", re.I)

PHASE_RANK = {"pre": 0, "intraday": 1, "close": 2}
PHASE_LABEL = {"pre": "개장 전", "intraday": "장중", "close": "마감"}


def market_of(title: str) -> str | None:
    """한 거래일 시황 기사면 시장("us"·"kr"), 아니면 None. 두 시장이 다 나오면 앞에 나온 쪽."""
    if not _MOVE.search(title) or _NOT_SESSION.search(title):
        return None
    us, kr = _US.search(title), _KR.search(title)
    if us and kr:
        return "us" if us.start() < kr.start() else "kr"
    return "us" if us else "kr" if kr else None


def _trading(m: Market, d: date) -> bool:
    return d.weekday() < 5 and d not in m.holidays


def _at(m: Market, d: date, t: time) -> datetime:
    return datetime.combine(d, t, m.tz)


def last_closed(m: Market, when: datetime) -> date:
    """when 에 이미 끝난 가장 최근 거래일."""
    d = when.astimezone(m.tz).date()
    while not (_trading(m, d) and _at(m, d, m.close) <= when):
        d -= timedelta(days=1)
    return d


def _next_open(m: Market, when: datetime) -> date:
    d = when.astimezone(m.tz).date()
    while not (_trading(m, d) and _at(m, d, m.open) > when):
        d += timedelta(days=1)
    return d


def session_of(market: str, title: str, published: datetime) -> tuple[date, str]:
    """(거래일, "pre"·"intraday"·"close"). 기사 시각으로 정하고, 제목의 선물·출발·마감 표시로 고친다."""
    m = MARKETS[market]
    local = published.astimezone(m.tz)
    d = local.date()
    if _PRE.search(title) and not _CLOSE.search(title):
        return _next_open(m, published), "pre"
    if _trading(m, d) and _at(m, d, m.open) <= published < _at(m, d, m.close):
        return d, ("close" if _CLOSE.search(title) and not _INTRA.search(title) else "intraday")
    return last_closed(m, published), "close"


def label(market: str, title: str, session: date, phase: str) -> str:
    if market == "us":
        name = "뉴욕증시"
    else:
        name = "코스닥" if "코스닥" in title and "코스피" not in title else "코스피"
    return f"{name} {session.day}일{MARKETS[market].local} {PHASE_LABEL[phase]}"


def judge(reports: list[dict], ref: datetime) -> dict[str, dict]:
    """reports: [{"id", "market", "title", "published"(aware datetime)}] — 지면 후보 시황 기사(이슈마다 가장 새 기사).
    ref: 발행 기준 시각. 돌려주는 값: id → {"keep": bool, "why": str, "asof": 표시, "session", "phase"}."""
    out: dict[str, dict] = {}
    best: dict[str, tuple] = {}
    for r in reports:
        s, ph = session_of(r["market"], r["title"], r["published"])
        r["_key"] = (s, PHASE_RANK[ph])
        out[r["id"]] = {"keep": True, "why": "", "asof": label(r["market"], r["title"], s, ph), "session": s.isoformat(), "phase": ph}
        if r["_key"] > best.get(r["market"], (date.min, -1)):
            best[r["market"]] = r["_key"]
    for r in reports:
        m = MARKETS[r["market"]]
        latest = last_closed(m, ref)
        s, rank = r["_key"]
        o = out[r["id"]]
        if s < latest:
            o.update(keep=False, why=f"지난 거래일({s.isoformat()}) 소식 — 기준 시각에 이미 {latest.isoformat()} 장이 끝남")
        elif r["_key"] < best[r["market"]]:
            o.update(keep=False, why=f"같은 시장의 더 새 소식({o['asof']} → {best[r['market']][0].isoformat()} "
                                     f"{[k for k, v in PHASE_RANK.items() if v == best[r['market']][1]][0]})이 있음")
    return out


def apply(scored: list, articles: dict, ref: datetime) -> tuple[list, dict]:
    """편집 전 이슈 목록에 적용: 지난·앞선 시황 이슈를 빼고, 남는 시황 이슈는 가장 새 시황 기사를 대표로 삼아 시점 표시를 단다.
    시황 이슈 = 대표 제목이 시황이거나, 묶인 기사 절반 이상이 시황. 돌려주는 값: (남은 이슈, 통계)."""
    reports, newest = [], {}
    for s in scored:
        arts = [articles[i] for i in s.issue.article_ids if i in articles and articles[i].published]
        mk = [(a, market_of(a.title)) for a in arts]
        mk = [(a, m) for a, m in mk if m]
        rep = articles.get(s.issue.rep_article)
        if not mk or not ((rep and market_of(rep.title)) or len(mk) * 2 >= len(arts)):
            continue

        def key(am):
            a, m = am
            ses, ph = session_of(m, a.title, datetime.fromisoformat(a.published))
            return (ses, PHASE_RANK[ph], a.published)
        a, m = max(mk, key=key)
        newest[s.issue.id] = a
        reports.append({"id": s.issue.id, "market": m, "title": a.title, "published": datetime.fromisoformat(a.published)})
    verdict = judge(reports, ref)
    by_id = {s.issue.id: s for s in scored}
    mkt = {r["id"]: r["market"] for r in reports}
    # 같은 시장·같은 거래일·같은 시점으로 남는 이슈는 점수 높은 하나에 합친다 (S29a — 뉴욕 22일 마감이 이슈 여럿으로 갈라져 따로 실림)
    hosts: dict[tuple, object] = {}
    for r in sorted(reports, key=lambda r: -by_id[r["id"]].final):
        v = verdict[r["id"]]
        if v["keep"]:
            hosts.setdefault((r["market"], v["session"], v["phase"]), by_id[r["id"]])
    latest: dict[str, tuple] = {}   # 시장 → (시점 키, 그 시장 가장 새 시점의 대표 이슈)
    for (m, ses, ph), h in hosts.items():
        k = (ses, PHASE_RANK[ph])
        if m not in latest or k > latest[m][0]:
            latest[m] = (k, h)
    kept, dropped, switched, merged, attached = [], [], 0, 0, 0
    for s in scored:
        v = verdict.get(s.issue.id)
        if v is None:
            kept.append(s)
            continue
        a, m = newest[s.issue.id], mkt[s.issue.id]
        if not v["keep"]:
            dropped.append(f"{s.issue.title[:40]} — {v['why']}")
            if m in latest:   # 빠진 지난·앞선 시황은 그 시장 최신 이슈의 "앞선 보도"로 (S29a·b)
                add_update(latest[m][1], a, v["asof"])
                attached += 1
            continue
        host = hosts[(m, v["session"], v["phase"])]
        if host is not s:
            host.issue.article_ids += [i for i in s.issue.article_ids if i not in host.issue.article_ids]
            merged += 1
            continue
        if a.id != s.issue.rep_article:   # 묶음 안의 더 새 시황 기사를 대표로 (제목·리드·링크)
            s.issue.rep_article, s.issue.title = a.id, a.title
            switched += 1
        s.issue.extra["asof"] = v["asof"]
        kept.append(s)
    return kept, {"reports": len(reports), "dropped": dropped, "switched": switched, "merged": merged, "attached": attached}


def add_update(host, a, asof: str | None = None) -> None:
    """host 이슈에 앞선 보도 한 줄 (S29a): 시각·제목·매체·주소. 같은 주소는 한 번."""
    ups = host.issue.extra.setdefault("updates", [])
    if any(u["url"] == a.url for u in ups):
        return
    ups.append({"published": a.published, "title": a.title, "source": a.source, "url": a.url, "lang": a.lang, "asof": asof})
