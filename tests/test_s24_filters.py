"""S24d 내용 없는 기사 거르기: 제목이 매체 이름·기호뿐인 기사, AI 가 "새 내용 없음"이라 한 이슈."""
from datetime import date

from pipeline.llm import Budget, enrich, no_news
from pipeline.settings import load_interests
from pipeline.textutil import empty_title
from tests.test_analysis import GOOD, cfg, item, runner_with

NAMES = frozenset({"중앙일보", "조선일보", "CNN"})


def test_empty_title():
    for t in ["- 중앙일보", "중앙일보", "[속보]", "  -  ", "CNN - 중앙일보", "(종합) - 조선일보", "AB", "[단독] 속"]:
        assert empty_title(t, NAMES), t
    for t in ["CJ, 중앙일보 인수전 참여", "이 대통령 조문", "Macron calls for calm", "중앙일보 매각 본입찰", "G7 개막", "[사설] 밤 사설"]:
        assert not empty_title(t, NAMES), t


# 10/19호에서 다른 이슈로 갈라졌던 같은 기사 / 흔한 낱말만 겹친 다른 기사 (S24c)
SAME = [("김민석, 지역축제 공연 끊고 인사말… ‘과잉 의전’ 논란", "가수 공연 끊고 마이크 잡은 김민석"),
        ("'초전박살' KIA, 이틀 연속 LG 꺾고 준PO 2연승…앞으로 1승", "KIA, LG에 2연승 거두고 PO 진출까지 1승…전상현 MVP"),
        ("“아빠, 꼭 다시 만나요”…순직 소방관 영정 앞에 놓인 7세딸의 손편지", "“아빠, 나중에 꼭 다시 만나요” 순직 소방관 7살 딸의 눈물 편지"),
        ("부산 상어 '부캉이' 지느러미 상처 관찰…누적 방문객 160만명(종합)", "‘부캉이’ 부산 체류 한 달째… 누적 방문객 154만명 넘었다")]
DIFFERENT = [("Leeds United v Manchester United: Premier League – live", "Nottingham Forest vs Arsenal LIVE: Premier League"),
             ("[부고] 김민철(제너시스BBQ그룹 커뮤니케이션실 상무)씨 장모상", "[부고] 오용하(롯데지주 HR혁신실 상무)씨 장모상")]
OTHERS = ["Chelsea v Everton: Premier League – live", "[부고] 박영수(삼성전자 상무)씨 장모상", "이 대통령, 순직 소방관 조문"]


def test_same_title_on_real_pairs():
    from pipeline.edit import common_title_words, same_title
    common = common_title_words([t for p in SAME + DIFFERENT for t in p] + OTHERS)
    for a, b in SAME:
        assert same_title(a, b, common), a
    for a, b in DIFFERENT:
        assert not same_title(a, b, common), a


def test_editorial_groups_do_not_chain():
    """S24e: A~B, B~C 만 닮고 A·C 는 다른 사안이면 셋을 한 묶음으로 만들지 않는다 (예전 단일 연결)."""
    from pipeline.opinion import group_editorials
    from tests.test_opinion import art
    a = art(1, "조선일보", "보수", "[사설] 의대 증원 갈등 장기화, 정부가 대화 나서야", opinion="editorial")
    b = art(2, "한겨레", "진보", "[사설] 의대 증원 갈등, 전공의 복귀 해법 찾아야", opinion="editorial")
    c = art(3, "경향신문", "진보", "[사설] 전공의 복귀 해법, 수련 병원 지원부터", opinion="editorial")
    d = art(4, "동아일보", "보수", "[사설] 국민연금 개혁 더는 미룰 수 없다", opinion="editorial")
    groups = group_editorials([a, b, c, d])
    assert all(len(g) == 2 for g in groups) and groups          # 셋이 한 묶음이 되지 않음
    assert not any({a.id, c.id} <= {e.id for e in g} for g in groups)
    assert not any(d.id in {e.id for e in g} for g in groups)   # 관계없는 사설은 혼자


def test_no_news_phrases():
    for s in ["중앙일보 인수전 관련 새 정보 없음", "중앙일보 인수전, 이번 기사에선 새 내용 없음", "새로운 사실은 확인되지 않았다",
              "새 소식이 없다", "새 내용 확인 안 돼"]:
        assert no_news({"brief": s}), s
    assert no_news({"brief": "개각 발표", "empty": True})
    assert not no_news(GOOD)
    assert not no_news({"brief": "새 정부 출범, 내각 발표"})


def test_no_news_issue_dropped_from_page(tmp_path):
    stale = dict(GOOD, brief="중앙일보 인수전 관련 새 정보 없음")
    ed = {"sections": {"front": [item("top"), item("i1", url="https://a.test/2")], "economy": [item("i2", url="https://a.test/3")]},
          "compare": [], "stats": {}}
    out = enrich(ed, cfg(), load_interests().foreign_display, tmp_path / "llm.json",
                 Budget(tmp_path / "u.json", date(2026, 10, 19), 10),
                 runner=runner_with({"top": stale, "i1": GOOD, "i2": stale}, []))
    assert [it["issue_id"] for it in out["sections"]["front"]] == ["top", "i1"]   # 1면 톱은 그대로
    assert out["sections"]["economy"] == []
    assert "analysis" not in out["sections"]["front"][0].get("llm", {})       # 정리·경과는 남기지 않음
    assert out["stats"]["llm"]["analysis"]["rejected"]["i2"] == "새 내용 없음"
    # 캐시로 다시 돌려도 내려간다
    ed2 = {"sections": {"economy": [item("i2", url="https://a.test/3")]}, "compare": [], "stats": {}}
    out2 = enrich(ed2, cfg(), load_interests().foreign_display, tmp_path / "llm.json",
                  Budget(tmp_path / "u.json", date(2026, 10, 19), 10), runner=runner_with({}, []))
    assert out2["sections"]["economy"] == []
