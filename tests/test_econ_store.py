"""S33 경제 해설 보관·재사용: data/econ 기록·메꾸기, 지난 해설 짝짓기, 프롬프트의 "지난 해설" 블록 (네트워크·AI 없음)."""
import json
from datetime import date

from pipeline import econ_store
from pipeline.llm import ECON_PROMPT, econ_dive
from tests.test_econ import DIVE, cfg, guarded_with, item, runner

FED = ["inflation", "rate", "reserve", "fed", "interest", "federal", "hold", "steady"]
KO = ["기준", "준금", "금리", "동결", "한국", "국은", "은행"]
OTHER = ["football", "league", "match", "goal", "season"]


def eco(iid, dive=DIVE, n_arts=1, **kw):
    it = item(iid, **kw)
    it["articles"] = [{**it["articles"][0], "source": f"매체{k}", "url": f"https://a.test/{iid}/{k}?utm_source=x",
                       "lang": "en" if k else "ko", "lead": "리드 문장", "id": f"a{iid}{k}"} for k in range(n_arts)]
    if dive:
        it["llm"] = {"econ": dive, "analysis": {"summary": "요약"}}
    return it


def edition(day, items):
    return {"edition": day, "sections": {"economy": items}, "compare": []}


def history(data, day, sigs):
    (data / "history").mkdir(parents=True, exist_ok=True)
    (data / "history" / f"{day}.json").write_text(json.dumps({"issues": [{"id": k, "signature": v} for k, v in sigs.items()]}),
                                                   encoding="utf-8")


def test_record_fields_links_no_body(tmp_path):
    history(tmp_path, "2026-10-30", {"1": FED})
    ed = edition("2026-10-30", [eco("1", n_arts=5), eco("2", dive=None)])
    path = econ_store.write(tmp_path, "2026-10-30", ed)
    rec = json.loads(path.read_text(encoding="utf-8"))
    assert path == tmp_path / "econ" / "2026-10-30.json" and rec["v"] == 1 and rec["edition"] == "2026-10-30"
    assert [x["issue_id"] for x in rec["items"]] == ["1"]           # 해설 없는 기사는 빠진다
    x = rec["items"][0]
    assert x["signature"] == FED and x["theory"] == DIVE["theory"] and x["watch"] == DIVE["watch"] and x["topic"] == "economy"
    assert len(x["articles"]) == 3 and x["articles"][0]["lang"] == "ko"   # 3건 상한, 한국어 먼저
    assert set(x["articles"][0]) == {"source", "title", "url", "published", "lang"} and "utm_source" not in x["articles"][0]["url"]
    assert "리드" not in path.read_text(encoding="utf-8")            # 리드·본문 없음


def test_no_file_without_commentary_and_missing_history(tmp_path):
    assert econ_store.write(tmp_path, "2026-10-30", edition("2026-10-30", [eco("1", dive=None)])) is None
    assert not (tmp_path / "econ").exists()
    path = econ_store.write(tmp_path, "2026-10-30", edition("2026-10-30", [eco("1")]))   # history 없으면 signature 빈 목록
    assert json.loads(path.read_text(encoding="utf-8"))["items"][0]["signature"] == []


def test_backfill_only_missing(tmp_path):
    raw, data = tmp_path / "raw", tmp_path / "data"
    raw.mkdir()
    for day in ("2026-10-30", "2026-10-31", "2026-11-01"):
        (raw / f"{day}.edition.json").write_text(json.dumps(edition(day, [eco("1", dive=None if day == "2026-11-01" else DIVE)])),
                                                 encoding="utf-8")
    (raw / "2026-10-29.edition.json").write_text("\x00\x00", encoding="utf-8")   # 깨진 파일은 건너뜀
    (data / "econ").mkdir(parents=True)
    (data / "econ" / "2026-10-30.json").write_text('{"keep": 1}', encoding="utf-8")
    assert econ_store.backfill(raw, data) == ["2026-10-31"]
    assert (data / "econ" / "2026-10-30.json").read_text(encoding="utf-8") == '{"keep": 1}'   # 있는 것은 그대로
    assert not (data / "econ" / "2026-11-01.json").exists()
    assert econ_store.backfill(raw, data) == []                                               # 두 번째는 할 일 없음


def _store(data, day, sigs):
    history(data, day, sigs)
    econ_store.write(data, day, edition(day, [eco(k) for k in sigs]))


def test_match_similar_only_and_window(tmp_path):
    _store(tmp_path, "2026-10-29", {"fed": FED, "ko": KO, "ball": OTHER})
    _store(tmp_path, "2026-11-02", {"today": FED})                 # 오늘 호는 빼고
    _store(tmp_path, "2026-04-01", {"old": FED})                   # 180일 넘은 것도 빼고
    past = econ_store.load_past(tmp_path, date(2026, 11, 2))
    assert {p["issue_id"] for p in past} == {"fed", "ko", "ball"} and all(p["date"] == "2026-10-29" for p in past)
    assert [p["issue_id"] for p in econ_store.match(["fed", "rate", "inflation", "hike", "dollar"], past)] == ["fed"]
    assert [p["issue_id"] for p in econ_store.match(["한국", "국은", "은행", "기준", "준금", "금리", "인상"], past)] == ["ko"]
    assert econ_store.match(["fed", "rate", "apple"], past) == []  # 영어 낱말 둘뿐이면 짝짓지 않음 (LATIN_ONLY_MIN)
    assert econ_store.match(["바이오", "제약"], past) == [] and econ_store.match([], past) == []


def test_past_for_uses_today_history(tmp_path):
    _store(tmp_path, "2026-10-29", {"fed": FED})
    history(tmp_path, "2026-10-30", {"t1": FED[:5], "t2": OTHER})
    got = econ_store.past_for([item("t1"), item("t2")], tmp_path, date(2026, 10, 30))
    assert list(got) == ["t1"] and got["t1"][0]["date"] == "2026-10-29"
    assert econ_store.past_for([item("t1")], tmp_path / "empty", date(2026, 10, 30)) == {}


def test_prompt_carries_past_block_and_rule():
    items = [item("1", final=0.9), item("2", final=0.8)]
    past = {"1": [{"date": "2026-10-23", "title": "한은 기준금리 동결", "concepts": ["금리 인상 사이클"], "theory": "지난 이론 문장",
                   "practice": "지난 실제 문장", "analysis": ["가", "나", "다"], "signature": KO, "articles": []}]}
    prompts = []
    _, st = econ_dive(items, {}, cfg(), {}, guarded_with(runner({"1": DIVE, "2": DIVE}, prompts), []), [], None, past)
    block = prompts[0][prompts[0].index("<data>"):]
    assert "지난 해설" in block and "2026-10-23" in block and "지난 이론 문장" in block and '"다"' not in block   # 분석은 앞 2개만
    assert block.count("지난 해설") == 1 and st["past"] == 1           # 짝 없는 기사엔 블록 없음
    for rule in ("참고만", "달라진 점", "그대로 옮기지 말 것"):
        assert rule in ECON_PROMPT
