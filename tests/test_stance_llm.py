"""S7 입장 차이(무토큰)와 LLM 훅."""
import json
import subprocess
import sys
from collections import Counter
from datetime import date

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
