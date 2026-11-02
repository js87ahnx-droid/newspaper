"""S37 중국은 지금 — 후보 고르기(watch)와 AI 분석 검사(analyze)."""
from pipeline.china import AGENDA_MAX, analyze, watch
from pipeline.collect import Article


def art(i, source, country, title, sections=("top",), opinion=None, lean="중도"):
    return Article(id=i, url=f"https://x.test/{i}", source=source, country=country, lean=lean, media_type="종합지", weight=1,
                   paywall=False, kind="rss", title=title, lead="리드" * 20, lang="zh" if country == "CN" else "en",
                   published=f"2026-11-03T0{len(i) % 9}:00:00Z", date_source="feed", sections=list(sections), opinion=opinion)


def row(a: Article) -> dict:
    return {"id": a.id, "source": a.source, "country": a.country, "lean": a.lean, "lang": a.lang, "title": a.title,
            "lead": a.lead, "url": a.url}


def item(iid, arts, final, reserve=False, headline_by=None):
    return {"issue_id": iid, "title": f"제목 {iid}", "articles": [row(a) for a in arts], "scores": {"final": final},
            "reserve": reserve, "headline_by": headline_by or {}}


PD_TOP = art("p1", "인민일보", "CN", "坚定不移推进科技自立自强", ("top",), lean="관영")
PD_POL = art("p2", "인민일보", "CN", "外交部回应美方出口管制", ("politics",), lean="관영")
PD_OP = art("p3", "인민일보", "CN", "霸凌行径注定失败（人民论坛）", ("opinion",), opinion="column", lean="관영")
WSJ = art("w", "Wall Street Journal", "US", "China chip stockpile", lean="보수")
FT = art("f", "Financial Times", "GB", "ASML sales hit")
NK = art("n", "Nikkei Asia", "JP", "Japan suppliers")
YH = art("y", "연합뉴스", "KR", "반도체 예외")
XH = art("x", "신화통신", "CN", "商务部", lean="관영")


def setup():
    arts = [PD_TOP, PD_POL, PD_OP, WSJ, FT, NK, YH, XH,
            art("pic", "인민일보", "CN", "图片报道", lean="관영"), art("ed", "인민일보", "CN", "责编：张三 邮箱：a@b.c", lean="관영")]
    articles = {a.id: a for a in arts}
    edition = {"sections": {
        "international": [item("chip", [PD_TOP, WSJ, FT, NK], 0.9),            # 후보: top + 3개국
                          item("one", [PD_TOP, WSJ], 0.95),                     # 중국 밖 1개국뿐
                          item("res", [PD_OP, WSJ, FT], 0.99, reserve=True)],   # 예비 기사
        "politics": [item("pol", [PD_POL, WSJ, YH], 0.8),                       # 인민일보가 politics 피드뿐 → 아님
                     item("polh", [PD_POL, WSJ, YH], 0.7, headline_by={"인민일보": [1, "homepage"]}),   # 헤드라인이면 후보
                     item("op", [PD_OP, FT, YH, XH], 0.85),                     # 논평 + 2개국 (신화는 중국이라 안 셈)
                     item("none", [WSJ, FT, NK], 0.99)],                       # 인민일보 없음
    }}
    return edition, articles


def test_watch_candidates_and_agenda():
    edition, articles = setup()
    w = watch(edition, articles)
    assert [c["issue_id"] for c in w["candidates"]] == ["chip", "op", "polh"]
    assert w["candidates"][1]["foreign_countries"] == ["GB", "KR"]
    titles = [a["title"] for a in w["agenda"]]
    assert set(titles) == {PD_TOP.title, PD_POL.title, PD_OP.title}       # 사진 설명·편집자 표시 빼고 인민일보만
    assert all(set(a) == {"id", "title", "sections", "opinion", "url"} for a in w["agenda"])   # 리드·본문 없음


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
