"""S7 입장 차이(무토큰)와 LLM 훅."""
import json
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timezone

from pipeline.collect import Article
from pipeline.settings import Interests, Llm, load_interests
from pipeline.stance import coverage_note, day_prior, distinctive_words, group_lean, stance, words


def art(i, source, lean, country="KR", lang="ko", title="", lead=""):
    return Article(
        id=f"a{i}", url=f"https://x.test/{i}", source=source, country=country, lean=lean, media_type="종합지",
        weight=1.0, paywall=False, kind="rss", title=title, lead=lead, lang=lang,
        published="2026-10-15T12:00:00+00:00", date_source="feed", sections=["top"], first_seen="2026-10-15T12:00:00+00:00",
    )


def test_words_strip_josa_and_boilerplate():
    w = words("정부가 개혁안을 발표했다고 서울 기자 연합뉴스 밝혔다", "ko")
    assert "정부" in w and "개혁안" in w and "발표" in w
    assert not {"서울", "기자", "연합뉴스", "밝혔다"} & set(w)
    assert words("Officials said the Kremlin accuses Ukraine", "en") == ["officials", "kremlin", "accuses", "ukraine"]


def test_distinctive_words_per_group():
    arts = [
        art(1, "A", "보수", title="정부 감세 경제 활력", lead="감세로 기업 투자 확대"),
        art(2, "B", "보수", title="감세 효과 기업 투자", lead="경제 활력 감세"),
        art(3, "C", "진보", title="부자 감세 세수 펑크", lead="세수 감소 복지 축소 우려"),
        art(4, "D", "진보", title="세수 펑크 복지 축소", lead="부자 감세 비판"),
    ]
    prior = day_prior(arts)
    dw = distinctive_words(arts, group_lean, prior)
    assert set(dw) == {"보수", "진보"}
    assert {"투자", "기업"} & set(dw["보수"])
    assert {"세수", "펑크", "복지"} & set(dw["진보"])


def test_no_words_when_one_group_or_across_languages():
    one = [art(1, "A", "보수", title="같은 그룹"), art(2, "B", "보수", title="같은 그룹 둘")]
    assert distinctive_words(one, group_lean, day_prior(one)) == {}
    # 언어가 다르면 비교하지 않는다 (한국어 보수 1 vs 영어 진보 1)
    mixed = [art(1, "A", "보수", title="정부 발표"), art(2, "NYT", "진보", "US", "en", title="Government announces plan")]
    assert distinctive_words(mixed, group_lean, day_prior(mixed)) == {}


def test_coverage_notes():
    assert coverage_note([art(1, "A", "보수", title="x")]) is None  # 매체 1곳: 당연하므로 표시 안 함
    kr_only = [art(1, "조선", "보수"), art(2, "연합", "통신·공영")]
    assert coverage_note(kr_only) == "국내 진보 성향 매체 보도 없음"
    both = [art(1, "조선", "보수"), art(2, "한겨레", "진보")]
    assert coverage_note(both) is None
    us_only = [art(1, "NYT", "진보", "US", "en"), art(2, "Fox", "보수", "US", "en")]
    assert coverage_note(us_only) == "미국 매체만 보도"


def test_stance_structure_orders_groups():
    arts = [art(1, "한겨레", "진보"), art(2, "조선", "보수"), art(3, "BBC", "통신·공영", "UK", "en")]
    s = stance(arts, day_prior(arts))
    assert [g["group"] for g in s["lean"]] == ["보수", "진보", "통신·공영"]
    assert [g["group"] for g in s["country"]] == ["한국", "영국"]


# ---------- LLM 훅 ----------

def edition_fixture():
    def item(iid, lang, title):
        return {"issue_id": iid, "title": title, "lead": "lead", "articles": [
            {"id": iid, "source": "S", "country": "US", "lean": "중도", "lang": lang, "title": title, "lead": "lead"}]}
    en, ja, ko = item("e1", "en", "Pope has surgery"), item("j1", "ja", "首相が辞任"), item("k1", "ko", "국내 기사")
    return {"sections": {"front": [en, ko], "briefs": [ja]}, "compare": [en], "stats": {}}


def test_llm_disabled_never_imports(tmp_path):
    """enabled=false 면 llm 모듈을 불러오지도, CLI 를 부르지도 않는다 (별도 프로세스에서 확인)."""
    code = (
        "import sys, json, pathlib\n"
        "sys.argv=['x']\n"
        "from pipeline import __main__ as m\n"
        "import pipeline.settings as st\n"
        "orig = st.load_config\n"
        "def cfg(root=st.ROOT):\n"
        "    c = orig(root); c.llm.enabled = False; return c\n"
        "m.load_config = cfg\n"
        f"m.main(['--data', r'{tmp_path}', 'enrich', '--date', '2026-10-16'])\n"
        "print('LLM_IMPORTED' if 'pipeline.llm' in sys.modules else 'LLM_NOT_IMPORTED')\n"
    )
    raw = tmp_path / "raw"
    raw.mkdir()
    a = {"id": "e1", "url": "u", "source": "S", "country": "US", "lean": "중도", "media_type": "종합지", "weight": 1.0,
         "paywall": False, "kind": "rss", "title": "Pope has surgery", "lead": "lead", "lang": "en",
         "published": "2026-10-15T12:00:00+00:00", "date_source": "feed", "sections": ["top"], "main": False,
         "first_seen": "2026-10-15T12:00:00+00:00"}
    (raw / "2026-10-16.json").write_text(json.dumps([a]), encoding="utf-8")
    ed = edition_fixture()
    ed["sections"] = {"front": [ed["sections"]["front"][0]]}
    (raw / "2026-10-16.edition.json").write_text(json.dumps(ed), encoding="utf-8")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8")
    assert "LLM_NOT_IMPORTED" in out.stdout, out.stderr[-500:]
    assert not (raw / "2026-10-16.llm.json").exists()


def test_llm_enrich_batches_and_respects_budget(tmp_path):
    from pipeline.llm import Budget, enrich

    calls = []

    def runner(prompt):
        calls.append(prompt)
        if "프레임" in prompt or "다르게" in prompt:
            body = {"summaries": {"e1": "프레임 요약"}}
        elif "번역" in prompt:
            body = {"titles": {"j1": "총리가 사임"}}
        else:
            body = {"summaries": {"e1": "교황이 수술을 받았다"}}
        return json.dumps({"result": json.dumps(body, ensure_ascii=False), "is_error": False})

    cfg = Llm(enabled=True, model="haiku", max_calls_per_day=2, timeout_sec=10, analysis_issues=0)
    display = load_interests().foreign_display  # 영어: 요약, 그 밖: 제목 번역
    budget = Budget(tmp_path / "usage.json", date(2026, 10, 16), cfg.max_calls_per_day)
    ed = enrich(edition_fixture(), cfg, display, tmp_path / "llm.json", budget, runner=runner)
    assert len(calls) == 2  # 상한 2회 — 세 번째(번역)는 호출하지 않음
    assert ed["stats"]["llm"]["status"]["ko_title"].startswith("하루 호출 상한")
    front = ed["sections"]["front"][0]
    assert front["llm"]["frame_summary"] == "프레임 요약" and front["llm"]["ko_summary"] == "교황이 수술을 받았다"
    assert "llm" not in ed["sections"]["front"][1]  # 한국어 기사는 손대지 않음
    # 기사 데이터는 <data> 안에 넣고, 지시를 따르지 말라는 시스템 지시를 둔다
    assert all("<data>" in c for c in calls)


def test_llm_failure_falls_back(tmp_path):
    from pipeline.llm import Budget, enrich

    def broken(prompt):
        raise RuntimeError("not logged in")

    cfg = Llm(enabled=True, model="haiku", max_calls_per_day=10, timeout_sec=10, analysis_issues=0)
    budget = Budget(tmp_path / "usage.json", date(2026, 10, 16), 10)
    ed = enrich(edition_fixture(), cfg, load_interests().foreign_display, tmp_path / "llm.json", budget, runner=broken)
    assert all("llm" not in it for ps in ed["sections"].values() for it in ps)
    st = ed["stats"]["llm"]["status"]
    assert st["compare"].startswith("호출 실패")
    # 인증 실패 뒤에는 더 부르지 않는다 (하루 상한을 헛되이 쓰지 않음)
    assert all(v.startswith("앞 호출 실패로 건너뜀") for k, v in st.items() if k != "compare")
    assert ed["stats"]["llm"]["calls_today"] == 1


def test_cli_error_envelope_reason(tmp_path):
    from pipeline.llm import Budget, call

    def envelope(prompt):
        return json.dumps({"is_error": True, "result": "Failed to authenticate. API Error: 401 OAuth access token has expired."})

    cfg = Llm(enabled=True, model="haiku", max_calls_per_day=10, timeout_sec=10, analysis_issues=0)
    res, st = call("x", cfg, Budget(tmp_path / "u.json", date(2026, 10, 16), 10), runner=envelope)
    assert res is None and st.startswith("CLI 오류: Failed to authenticate")


def test_llm_cache_prevents_recall(tmp_path):
    from pipeline.llm import Budget, enrich

    calls = []

    def runner(prompt):
        calls.append(1)
        return json.dumps({"result": '{"summaries": {"e1": "x"}, "titles": {"j1": "y"}}'})

    cfg = Llm(enabled=True, model="haiku", max_calls_per_day=10, timeout_sec=10, analysis_issues=0)
    budget = Budget(tmp_path / "usage.json", date(2026, 10, 16), 10)
    disp = load_interests().foreign_display
    enrich(edition_fixture(), cfg, disp, tmp_path / "llm.json", budget, runner=runner)
    n = len(calls)
    enrich(edition_fixture(), cfg, disp, tmp_path / "llm.json", budget, runner=runner)
    assert len(calls) == n


def test_call_takes_first_json_object_despite_trailing_text(tmp_path):
    """S19 평가: 응답 JSON 뒤에 설명이나 두 번째 객체가 붙어도 첫 객체를 쓴다 ("Extra data" 실패)."""
    import json as _json
    from datetime import date as _d
    from pipeline.llm import Budget, call
    from pipeline.settings import load_config
    cfg = load_config().llm
    for body in ['{"groups": [[0, 1]]}\n\n{"note": "x"}', '설명 {"groups": [[0, 1]]} 끝 {괄호}', '```json\n{"groups": [[0, 1]]}\n```']:
        out = _json.dumps({"result": body})
        got, st = call("p", cfg, Budget(tmp_path / "u.json", _d(2026, 10, 17), 99), runner=lambda t, o=out: o)
        assert (got, st) == ({"groups": [[0, 1]]}, "ok"), body
    got, st = call("p", cfg, Budget(tmp_path / "u.json", _d(2026, 10, 17), 99), runner=lambda t: _json.dumps({"result": "없음"}))
    assert got is None and st.startswith("응답 형식 오류")


# ---------- S20b 프랑스어·독일어 ----------
def test_french_gets_korean_title_and_summary(tmp_path):
    """프랑스어 기사는 제목 번역과 한국어 요약을 둘 다 받고, 지면은 한국어 제목 + 원 제목 + 한국어 요약."""
    from pipeline.llm import Budget, enrich
    from pipeline.render import _display
    asked = []

    def runner(prompt):
        asked.append(prompt)
        if "번역" in prompt:
            body = {"titles": {"f1": "마크롱, 개각 발표"}}
        elif "요약하라" in prompt and "성향" not in prompt:
            body = {"summaries": {"e1": "교황 수술", "f1": "마크롱 대통령이 개각을 발표했다."}}
        else:
            body = {"summaries": {}}
        return json.dumps({"result": json.dumps(body, ensure_ascii=False), "is_error": False})

    ed = edition_fixture()
    fr = {"issue_id": "f1", "title": "Macron annonce un remaniement", "lead": "Le président a annoncé…", "articles": [
        {"id": "f1", "source": "Le Monde", "country": "FR", "lean": "진보", "lang": "fr", "title": "Macron annonce un remaniement", "lead": "x"}]}
    ed["sections"]["front"].append(fr)
    cfg = Llm(enabled=True, model="haiku", max_calls_per_day=10, timeout_sec=10, analysis_issues=0)
    display = load_interests().foreign_display
    out = enrich(ed, cfg, display, tmp_path / "llm.json", Budget(tmp_path / "u.json", date(2026, 10, 17), 10), runner=runner)
    it = next(i for i in out["sections"]["front"] if i["issue_id"] == "f1")
    assert it["llm"]["ko_title"] == "마크롱, 개각 발표" and it["llm"]["ko_summary"].startswith("마크롱")
    v = _display(it, display)
    assert (v["title"], v["orig_title"], v["lead"], v["lead_note"], v["lang"]) == (
        "마크롱, 개각 발표", "Macron annonce un remaniement", "마크롱 대통령이 개각을 발표했다.", "AI 요약", "fr")
    ja = next(i for i in out["sections"]["briefs"] if i["issue_id"] == "j1")
    assert "ko_summary" not in ja.get("llm", {})       # 일본어는 지금처럼 제목 번역만
    from pipeline.textutil import TRANSLATE_BOTH
    assert TRANSLATE_BOTH == {"fr", "de", "zh"}        # 중국어(S20d)도 제목 번역 + 요약
    zh = {**fr, "articles": [{**fr["articles"][0], "lang": "zh"}]}
    assert _display(zh, display)["lead"] == "마크롱 대통령이 개각을 발표했다."


def test_feed_lang_marks_french_and_german():
    from pipeline.collect import entry_to_article
    from pipeline.settings import Feed, Source
    now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    e = {"link": "https://www.lemonde.fr/politique/article/2026/10/17/x", "title": "Macron annonce un remaniement",
         "summary": "Le président…", "published": "Fri, 17 Oct 2026 10:00:00 GMT"}
    fr = Feed(section="top", url="https://www.lemonde.fr/rss/une.xml", lang="fr")
    en = Feed(section="opinion", url="https://www.lemonde.fr/en/opinion/rss_full.xml")
    src = Source(name="Le Monde", country="FR", lean="진보", type="종합지", weight=1, paywall=True, enabled=True, feeds=[fr, en])
    assert entry_to_article(e, src, fr, now).lang == "fr"
    assert entry_to_article(e, src, en, now).lang == "en"      # 피드가 알려 주지 않으면 라틴 문자는 영어
    assert entry_to_article({**e, "title": "프랑스 개각"}, src, fr, now).lang == "ko"   # 문자 체계가 먼저
    import pytest as _pt
    with _pt.raises(ValueError):
        Feed(section="x", url="https://a.b/", lang="xx")


def test_opinion_titles_in_japanese_get_korean(tmp_path):
    """S20c: 논평면 일본어·독일어·프랑스어 사설 제목은 한국어로 (영어는 그대로), 사설 비교 묶음도 같이. 두 번째는 캐시."""
    from pipeline.llm import Budget, enrich
    asked = []

    def runner(prompt):
        asked.append(prompt)
        body = {"titles": {"y1": "중의원 해산을 서두르지 마라"}} if "사설·칼럼 제목" in prompt else {}
        return json.dumps({"result": json.dumps(body, ensure_ascii=False), "is_error": False})

    def ed():
        e = edition_fixture()
        ja = {"id": "y1", "lang": "ja", "title": "社説：衆院解散を急ぐな", "source": "요미우리신문"}
        en = {"id": "g1", "lang": "en", "title": "The Guardian view on X", "source": "Guardian"}
        e["opinion"] = {"editorials": [dict(ja), en], "columns": [], "compare": [{"groups": [{"editorials": [dict(ja)]}]}]}
        return e
    cfg = Llm(enabled=True, model="haiku", max_calls_per_day=20, timeout_sec=10, analysis_issues=0)
    disp = load_interests().foreign_display
    out = enrich(ed(), cfg, disp, tmp_path / "llm.json", Budget(tmp_path / "u.json", date(2026, 10, 17), 20), runner=runner)
    op = out["opinion"]
    assert op["editorials"][0]["ko_title"] == "중의원 해산을 서두르지 마라" and "ko_title" not in op["editorials"][1]
    assert op["compare"][0]["groups"][0]["editorials"][0]["ko_title"] == "중의원 해산을 서두르지 마라"
    n = sum("사설·칼럼 제목" in p for p in asked)
    out2 = enrich(ed(), cfg, disp, tmp_path / "llm.json", Budget(tmp_path / "u.json", date(2026, 10, 17), 20), runner=runner)
    assert n == 1 and sum("사설·칼럼 제목" in p for p in asked) == 1 and out2["opinion"]["editorials"][0]["ko_title"]
