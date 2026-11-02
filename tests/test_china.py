"""S37 중국은 지금 — 후보 고르기(watch)와 AI 분석 검사(analyze)."""
import pytest

from pipeline.china import AGENDA_MAX, CHINA_RE, analyze, watch
from pipeline.collect import Article


def art(i, source, country, title, sections=("top",), opinion=None, lean="중도"):
    return Article(id=i, url=f"https://x.test/{i}", source=source, country=country, lean=lean, media_type="종합지", weight=1,
                   paywall=False, kind="rss", title=title, lead="리드" * 20, lang="zh" if country == "CN" else "en",
                   published=f"2026-11-03T0{len(i) % 9}:00:00Z", date_source="feed", sections=list(sections), opinion=opinion)


def row(a: Article) -> dict:
    return {"id": a.id, "source": a.source, "country": a.country, "lean": a.lean, "lang": a.lang, "title": a.title,
            "lead": a.lead, "url": a.url}


def item(iid, arts, final, reserve=False, headline_by=None):
    return {"issue_id": iid, "title": f"제목 {iid}", "lead": "리드", "topic": "international", "url": arts[0].url, "source": arts[0].source,
            "lean": arts[0].lean, "articles": [row(a) for a in arts], "scores": {"final": final},
            "reserve": reserve, "headline_by": headline_by or {}}


PD_TOP = art("p1", "인민일보", "CN", "坚定不移推进科技自立自强", ("top",), lean="관영")
PD_POL = art("p2", "인민일보", "CN", "外交部回应美方出口管制", ("politics",), lean="관영")
PD_OP = art("p3", "인민일보", "CN", "霸凌行径注定失败（人民论坛）", ("opinion",), opinion="column", lean="관영")
WSJ = art("w", "Wall Street Journal", "US", "China chip stockpile", lean="보수")
FT = art("f", "Financial Times", "GB", "ASML China sales hit")
NK = art("n", "Nikkei Asia", "JP", "Japan suppliers brace for China curbs")
YH = art("y", "연합뉴스", "KR", "중국 공장 반도체 예외")
FT2 = art("f2", "Financial Times", "GB", "Oil prices rise")      # 중국과 무관한 기사
NK2 = art("n2", "Nikkei Asia", "JP", "Yen slips")
YH2 = art("y2", "연합뉴스", "KR", "코스피 상승")
XH = art("x", "신화통신", "CN", "商务部", lean="관영")


def setup():
    arts = [PD_TOP, PD_POL, PD_OP, WSJ, FT, NK, YH, XH, FT2, NK2, YH2,
            art("pic", "인민일보", "CN", "图片报道", lean="관영"), art("ed", "인민일보", "CN", "责编：张三 邮箱：a@b.c", lean="관영")]
    articles = {a.id: a for a in arts}
    edition = {"sections": {
        "international": [item("chip", [PD_TOP, WSJ, FT, NK], 0.9),            # 후보: top + 3개국
                          item("one", [PD_TOP, WSJ], 0.95),                     # 중국 밖 1개국뿐
                          item("res", [PD_OP, WSJ, FT], 0.99, reserve=True)],   # 예비 기사
        "politics": [item("pol", [PD_POL, WSJ, YH], 0.8),                       # 중국 매체 + 2개국
                     item("polh", [PD_POL, WSJ, YH], 0.7),                      # 점수 4등 → 3개 상한에 걸림
                     item("op", [PD_OP, FT, YH, XH], 0.85),                     # 논평 + 2개국 (신화는 중국이라 안 셈)
                     item("none", [FT2, NK2, YH2], 0.99),                     # 중국과 무관
                     item("cnone", [XH, FT2, NK2, YH2], 0.98)],               # 중국 매체가 끼었을 뿐 제목은 무관 → 아님
    }}
    return edition, articles


def test_watch_candidates_and_agenda():
    edition, articles = setup()
    w = watch(edition, articles)
    assert [c["issue_id"] for c in w["candidates"]] == ["chip", "op", "pol"]
    assert w["candidates"][1]["foreign_countries"] == ["GB", "KR"]
    titles = [a["title"] for a in w["agenda"]]
    assert set(titles) == {PD_TOP.title, PD_POL.title, PD_OP.title}       # 사진 설명·편집자 표시 빼고 인민일보만
    assert all(set(a) == {"id", "title", "sections", "opinion", "url"} for a in w["agenda"])   # 리드·본문 없음


def test_watch_needs_paper_or_opinion_today():
    edition, articles = setup()
    for k in ("p1", "p3"):          # 그날 종이 인민일보·논평을 못 받음
        articles.pop(k)
    assert watch(edition, articles)["candidates"] == []


def test_china_related_by_title_only():
    edition, articles = setup()
    tw = item("tw", [art("t", "Reuters", "US", "Stocks fall"), FT2, NK2], 0.97)
    tw["title"] = "대만 증시 급락"                  # 이슈 제목만 중국 관련이어도
    edition["sections"]["international"].append(tw)
    assert watch(edition, articles)["candidates"][0]["issue_id"] == "tw"


@pytest.mark.parametrize("title,want", [("\"中 티베트서 규모 7.0 강진\"", True), ("美中 갈등", True), ("한중 정상회담", True),
                                        ("시진핑 연설", True), ("中東情勢が緊迫", False), ("大会を中止", False), ("오늘 중에 발표", False)])
def test_china_regex(title, want):
    assert bool(CHINA_RE.search(title)) == want


def test_watch_caps():
    edition, articles = setup()
    for k in range(AGENDA_MAX + 20):
        a = art(f"m{k}", "인민일보", "CN", f"标题{k}号新闻", lean="관영")
        articles[a.id] = a
    extra = [item(f"c{k}", [PD_TOP, WSJ, FT, NK], 0.5 + k / 100) for k in range(5)]
    edition["sections"]["international"] += extra
    w = watch(edition, articles)
    assert len(w["agenda"]) == AGENDA_MAX and len(w["candidates"]) == 3


GOOD = {"show": True, "issue_id": "chip", "title": "자립을 앞세운 인민일보", "lead": "피해보다 기술 굴기를 강조했다.",
        "emphasis": ["미국 조치의 부당성", "국산화 성과"], "omitted": ["수출 감소"], "keywords": ["自立自强", "新质生产力"],
        "compare": [{"source": "Wall Street Journal", "focus": "재고"}, {"source": "Financial Times", "focus": "장비사 매출"},
                    {"source": "신화통신", "focus": "중국 매체라 빠짐"}, {"source": "Le Monde", "focus": "자료에 없음"}],
        "agenda": ["장정 90주년"], "evidence": ["https://x.test/p1", "https://x.test/w", "https://evil.test/z"]}


def run(res, edition=None, articles=None, cache=None):
    edition, articles = (edition, articles) if edition else setup()
    w = watch(edition, articles)
    items = [it for ps in edition["sections"].values() for it in ps]
    calls = []

    def ask(prompt, system=None):
        calls.append(prompt)
        return (res, "ok") if res is not None else (None, "시간 초과")
    out, st = analyze(w, items, {}, cache if cache is not None else {}, ask)
    return out, st, calls


def test_analyze_cleans_good_answer():
    out, st, calls = run(GOOD)
    assert st == "실음" and len(calls) == 1
    assert "坚定不移推进科技自立自强" in calls[0] and "Nikkei Asia" in calls[0]
    assert out["keywords"] == ["自立自强"]                     # 제목에 없는 新质生产力 은 거름
    assert [c["source"] for c in out["compare"]] == ["Wall Street Journal", "Financial Times"]
    assert out["compare"][0]["country"] == "US"
    assert [e["url"] for e in out["evidence"]] == ["https://x.test/p1", "https://x.test/w"]
    assert out["evidence"][0]["source"] == "인민일보"


def test_analyze_rejects():
    assert run({**GOOD, "show": False, "reason": "평범함"})[:2] == (None, "안 실음: 평범함")
    assert run({**GOOD, "issue_id": "none"})[1] == "후보 밖 이슈"
    assert run({**GOOD, "compare": GOOD["compare"][2:]})[1] == "다른 나라 매체 비교가 2곳 미만"
    assert run({**GOOD, "lead": " "})[1] == "제목·요약 비어 있음"
    assert run({**GOOD, "evidence": ["https://x.test/w"]})[1] == "인민일보 근거 없음"
    assert run(None)[:2] == (None, "시간 초과")


def test_no_candidates_no_call_and_cache():
    edition, articles = setup()
    edition["sections"] = {"politics": [edition["sections"]["politics"][-1]]}
    out, st, calls = run(GOOD, edition, articles)
    assert (out, st, calls) == (None, "후보 없음", [])
    cache = {}
    run(GOOD, cache=cache)
    out, st, calls = run({"show": False}, cache=cache)       # 같은 후보면 다시 묻지 않는다
    assert st == "실음" and calls == []


def test_enrich_runs_china_and_llm_off_has_none(tmp_path):
    """S37d: enrich 가 china_watch 로 분석해 edition["china"] 에 둔다. 응답이 안 실음이면 없음, 본문은 캐시에 안 남는다."""
    import json
    from datetime import date

    from pipeline.llm import Budget, enrich
    from pipeline.settings import Llm, load_interests

    def build(answer):
        edition, articles = setup()
        edition.update({"compare": [], "stats": {}, "china_watch": watch(edition, articles)})
        calls = []

        def run(prompt):
            calls.append(prompt)
            return json.dumps({"result": json.dumps(answer if "중국은 지금" in prompt else {}, ensure_ascii=False)})
        cfg = Llm(enabled=True, model="haiku", max_calls_per_day=50, timeout_sec=10, analysis_issues=0, econ_issues=0)
        body = "본문 " * 100 + "비밀 문장"
        out = enrich(edition, cfg, load_interests().foreign_display, tmp_path / f"llm-{len(answer)}.json",
                     Budget(tmp_path / "u.json", date(2026, 11, 3), 50), runner=run, bodies={"https://x.test/w": body})
        return out, calls
    out, calls = build(GOOD)
    assert out["china"]["issue_id"] == "chip" and out["stats"]["llm"]["status"]["china"] == "실음"
    assert sum("중국은 지금" in c for c in calls) == 1 and any("비밀 문장" in c for c in calls)
    assert "비밀 문장" not in (tmp_path / f"llm-{len(GOOD)}.json").read_text(encoding="utf-8")
    out, _ = build({"show": False, "reason": "평범"})
    assert "china" not in out and out["stats"]["llm"]["status"]["china"] == "안 실음: 평범"
