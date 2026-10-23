"""증시 기사 시점 판정 (S28e, 2026-10-23 "23일 호에 21일 마감·22일 장중 기사가 22일 마감처럼 실렸다")."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from pipeline.cluster import Issue
from pipeline.collect import Article
from pipeline.market import apply, judge, last_closed, market_of, session_of, MARKETS

KST = ZoneInfo("Asia/Seoul")


def kst(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=KST)


REF_1023 = kst("2026-10-23 05:30")   # 10/23호 시간창 끝


@pytest.mark.parametrize("title,expect", [
    ("뉴욕증시, 스페이스X 실적에 기술주 강세…나스닥 1.1%↑(종합)", "us"),
    ("뉴욕증시, AI 불안에 하락 출발", "us"),
    ("Stock market today: Dow, S&P 500, Nasdaq slide as AI worries mount", "us"),
    ("[마감시황] 코스피, 외국인 매도에 3% 하락 마감", "kr"),
    ("Kospi ends higher on chip rally", "kr"),
    ("한국거래소, 코스닥 승강제 최상위에 절대평가제 도입 검토", None),      # 제도
    ("[뉴욕증시-주간전망] 흔들리는 AI 투심, 어디로 가야하오", None),         # 주간 전망
    ("나스닥 올라도 코스피는 급락…따로노는 한·미 증시, 왜?", None),          # 해설(물음표)
    ("美 나스닥 2주 새 1100P 하락…AI 기업들, 고금리에 빚 부담 커졌다", None),  # 여러 날
    ("[단독] 나스닥처럼 제한 없어…1군 기업 300곳 될 수도", None),
    ("[특징주] 엠에스바이오, 코스닥 입성 첫날 공모가 대비 70%↑(종합)", None),      # 종목 기사
    ("엔비디아와 '기판 동맹'…삼성전기, 코스피 약세에도 4% 상승", None),
    ("스페이스X·테슬라합병에 '중국' 복병…테슬라 중국공장 운명은?", None),
])
def test_market_of(title, expect):
    assert market_of(title) == expect


def test_session_us_dst():
    """서머타임(10월): 뉴욕 16:00 = 05:00 KST. 22일 06:14 KST 기사는 21일(현지) 마감, 22:53 KST 는 22일 장중."""
    assert session_of("us", "뉴욕증시, 기술주 강세…나스닥 1.1%↑(종합)", kst("2026-10-22 06:14")) == (date(2026, 10, 21), "close")
    assert session_of("us", "뉴욕증시, AI 불안에 하락 출발", kst("2026-10-22 22:53")) == (date(2026, 10, 22), "intraday")
    assert session_of("us", "나스닥 선물 약세", kst("2026-10-22 14:00")) == (date(2026, 10, 22), "pre")
    assert last_closed(MARKETS["us"], REF_1023) == date(2026, 10, 22)


def test_1023_case_drops_old_close_and_marks_intraday():
    reports = [
        {"id": "spacex", "market": "us", "title": "뉴욕증시, 스페이스X 실적에 기술주 강세…나스닥 1.1%↑(종합)", "published": kst("2026-10-22 06:14")},
        {"id": "fut", "market": "us", "title": "나스닥 선물 약세", "published": kst("2026-10-22 14:00")},
        {"id": "open", "market": "us", "title": "뉴욕증시, AI 불안에 하락 출발", "published": kst("2026-10-22 22:53")},
    ]
    v = judge(reports, REF_1023)
    assert v["spacex"]["keep"] is False and "지난 거래일" in v["spacex"]["why"]
    assert v["fut"]["keep"] is False                      # 같은 거래일 장중 소식이 더 새 것
    assert v["open"]["keep"] is True and v["open"]["asof"] == "뉴욕증시 22일(현지) 장중"


def test_close_report_supersedes_intraday():
    reports = [
        {"id": "open", "market": "us", "title": "뉴욕증시, AI 불안에 하락 출발", "published": kst("2026-10-22 22:53")},
        {"id": "close", "market": "us", "title": "뉴욕증시, AI 우려에 나스닥 2% 급락 마감", "published": kst("2026-10-23 05:12")},
    ]
    v = judge(reports, REF_1023)
    assert v["open"]["keep"] is False and v["close"]["keep"] is True
    assert v["close"]["asof"] == "뉴욕증시 22일(현지) 마감"


def test_est_session_still_open_at_0530():
    """서머타임 끝난 뒤(11월): 05:30 KST = 15:30 EST — 장이 아직 열려 있다. 장중 기사가 최신, 금요일 마감은 앞선 소식."""
    ref = kst("2026-11-10 05:30")
    assert last_closed(MARKETS["us"], ref) == date(2026, 11, 6)
    reports = [
        {"id": "fri", "market": "us", "title": "뉴욕증시, 기술주 반등…나스닥 1%↑(종합)", "published": kst("2026-11-09 06:10")},
        {"id": "mon", "market": "us", "title": "뉴욕증시, 금리 부담에 하락 출발", "published": kst("2026-11-10 00:30")},
    ]
    v = judge(reports, ref)
    assert session_of("us", reports[0]["title"], reports[0]["published"]) == (date(2026, 11, 6), "close")
    assert v["fri"]["keep"] is False and v["mon"]["keep"] is True and v["mon"]["asof"] == "뉴욕증시 9일(현지) 장중"


def test_weekend_keeps_friday_close():
    ref = kst("2026-10-26 05:30")   # 월요일 호 = 일요일 16:30 EDT
    assert last_closed(MARKETS["us"], ref) == date(2026, 10, 23)
    v = judge([{"id": "f", "market": "us", "title": "뉴욕증시, 혼조 마감", "published": kst("2026-10-24 06:10")}], ref)
    assert v["f"]["keep"] is True and v["f"]["asof"] == "뉴욕증시 23일(현지) 마감"


def test_kospi_sessions_and_holiday():
    v = judge([
        {"id": "old", "market": "kr", "title": "코스피 2% 상승 마감", "published": kst("2026-10-21 15:40")},
        {"id": "open", "market": "kr", "title": "코스피, 외국인 매도에 하락 출발", "published": kst("2026-10-22 09:05")},
        {"id": "close", "market": "kr", "title": "[마감시황] 코스피 3% 하락 마감", "published": kst("2026-10-22 15:40")},
        {"id": "kq", "market": "kr", "title": "코스닥, 2차전지 약세에 1% 하락 마감", "published": kst("2026-10-22 15:45")},
    ], REF_1023)
    assert [v[k]["keep"] for k in ("old", "open", "close", "kq")] == [False, False, True, True]
    assert v["close"]["asof"] == "코스피 22일 마감" and v["kq"]["asof"] == "코스닥 22일 마감"
    # 한글날(10/9 금) 휴장: 10/12(월) 05:30 의 가장 최근 장은 10/8
    assert last_closed(MARKETS["kr"], kst("2026-10-12 05:30")) == date(2026, 10, 8)


def _art(aid, title, published):
    return Article(id=aid, url=f"https://x/{aid}", source="연합뉴스", country="KR", lean="통신·공영", media_type="통신", weight=1.0,
                   paywall=False, kind="rss", title=title, lead="", lang="ko", published=published, date_source="feed")


def test_apply_switches_to_newest_report_and_drops_stale():
    from tests.test_edit import _sc
    arts = {a.id: a for a in [
        _art("a1", "뉴욕증시, 스페이스X 실적에 기술주 강세…나스닥 1.1%↑(종합)", "2026-10-21T21:14:00+00:00"),   # 22일 06:14 KST
        _art("a2", "뉴욕증시, AI 불안에 하락 출발", "2026-10-22T13:53:00+00:00"),                       # 22일 22:53 KST
        _art("b1", "뉴욕증시, 기술주 강세…나스닥 1.1%↑", "2026-10-21T21:20:00+00:00"),
        _art("c1", "한국거래소, 코스닥 승강제 최상위에 절대평가제 도입 검토", "2026-10-22T01:00:00+00:00"),
    ]}
    s_mixed = _sc("mixed", arts["a1"].title, [])
    s_mixed.issue.article_ids, s_mixed.issue.rep_article = ["a1", "a2"], "a1"   # 대표는 묵은 마감 기사, 묶음에 새 장중 기사
    s_old = _sc("old", arts["b1"].title, [])
    s_old.issue.article_ids, s_old.issue.rep_article = ["b1"], "b1"
    s_kq = _sc("kq", arts["c1"].title, [])
    s_kq.issue.article_ids, s_kq.issue.rep_article = ["c1"], "c1"
    kept, st = apply([s_mixed, s_old, s_kq], arts, REF_1023)
    assert [s.issue.id for s in kept] == ["mixed", "kq"]
    assert s_mixed.issue.rep_article == "a2" and s_mixed.issue.title == "뉴욕증시, AI 불안에 하락 출발"
    assert s_mixed.issue.extra["asof"] == "뉴욕증시 22일(현지) 장중" and "asof" not in s_kq.issue.extra
    assert st["reports"] == 2 and len(st["dropped"]) == 1 and st["switched"] == 1


def test_same_session_reports_merged_and_older_ones_become_updates():
    """S29a: 뉴욕 22일 마감 이슈 셋은 점수 높은 하나로 합치고, 빠진 21일 마감·22일 장중은 그 이슈의 앞선 보도(시각순)로."""
    from tests.test_edit import _sc
    rows = [
        ("old", "뉴욕증시, 스페이스X 실적에 기술주 강세…나스닥 1.1%↑(종합)", "2026-10-21T21:14:00+00:00", 3.0),
        ("open", "뉴욕증시, AI 불안에 하락 출발", "2026-10-22T13:53:00+00:00", 2.0),
        ("c1", "뉴욕증시, AI 불안 재고조에 기술주 급락…나스닥 2.6%↓", "2026-10-22T20:15:00+00:00", 1.0),
        ("c2", "AI 투자비 부담에 흔들린 뉴욕증시… 나스닥 2.6% 급락 마감", "2026-10-22T20:22:00+00:00", 1.5),
        ("c3", "뉴욕증시, AI투자 불안에 나스닥 2.6%↓…반도체지수 6.7% 급락(종합)", "2026-10-22T21:35:00+00:00", 0.5),
    ]
    arts, scored = {}, []
    for iid, title, pub, final in rows:
        arts[iid] = _art(iid, title, pub)
        s = _sc(iid, title, [], final=final)
        s.issue.article_ids, s.issue.rep_article = [iid], iid
        scored.append(s)
    kept, st = apply(scored, arts, REF_1023)
    assert [s.issue.id for s in kept] == ["c2"]                          # 같은 시점 셋 중 점수 높은 것
    host = kept[0]
    assert set(host.issue.article_ids) == {"c1", "c2", "c3"} and st["merged"] == 2
    ups = sorted(host.issue.extra["updates"], key=lambda u: u["published"])
    assert [u["title"] for u in ups] == [rows[0][1], rows[1][1]] and st["attached"] == 2
    assert ups[0]["asof"] == "뉴욕증시 21일(현지) 마감" and ups[1]["asof"] == "뉴욕증시 22일(현지) 장중"


def test_earlier_reports_inside_issue_become_updates():
    """S29b: 한 묶음 안의 22일 장중 기사는 22일 마감 대표 기사의 앞선 보도로."""
    from tests.test_edit import _sc
    arts = {a.id: a for a in [_art("o", "뉴욕증시, AI 불안에 하락 출발", "2026-10-22T13:53:00+00:00"),
                              _art("c", "뉴욕증시, AI 불안 재고조에 기술주 급락…나스닥 2.6%↓", "2026-10-22T20:15:00+00:00")]}
    s = _sc("x", arts["o"].title, [])
    s.issue.article_ids, s.issue.rep_article = ["o", "c"], "o"
    kept, _ = apply([s], arts, REF_1023)
    assert kept[0].issue.rep_article == "c"
    assert [(u["title"], u["asof"]) for u in kept[0].issue.extra["updates"]] == [(arts["o"].title, "뉴욕증시 22일(현지) 장중")]
