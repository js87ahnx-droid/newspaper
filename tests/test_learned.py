"""S30b 주간 관심 학습값 반영: 주에 한 번 받기, 잘못된 값 무시, interests.yaml 위에 덮어 읽기."""
from __future__ import annotations

import json
import re
import shutil
from datetime import date
from pathlib import Path

from pipeline import learned
from pipeline.interest import build_interest_table
from pipeline.settings import TOPICS, load_interests

ROOT = Path(__file__).resolve().parents[1]
RC = {"url": "https://r.example", "key": "k"}
PREFS = {"v": 1, "weights": {"economy": 2.5, "incidents": 0.0, "science": 1.2}, "keywords": ["원전", " HBM "],
         "updated": "2026-10-25T03:00:00.000Z"}


def _root(tmp_path: Path) -> Path:
    shutil.copy(ROOT / "interests.yaml", tmp_path / "interests.yaml")
    return tmp_path


def _ok(prefs=PREFS):
    calls = []

    def f(rc):
        calls.append(rc)
        return {"ok": True, "prefs": prefs}
    f.calls = calls
    return f


def test_same_week_fetches_once_next_week_again(tmp_path):
    root = _root(tmp_path)
    f = _ok()
    r1 = learned.learn(root, date(2026, 10, 26), RC, f)   # 월요일 (2026-W44)
    r2 = learned.learn(root, date(2026, 10, 30), RC, f)   # 같은 주 금요일
    assert r1["status"] == "반영" and r1["week"] == "2026-W44"
    assert r2["status"] == "이번 주 이미 반영" and len(f.calls) == 1
    r3 = learned.learn(root, date(2026, 11, 2), RC, f)    # 다음 주
    assert r3["status"] == "반영" and len(f.calls) == 2
    saved = json.loads(learned.learned_path(root).read_text(encoding="utf-8"))
    assert saved["week"] == "2026-W45" and saved["keywords"] == ["원전", "HBM"] and saved["weights"]["economy"] == 2.5


def test_bad_or_missing_answers_change_nothing(tmp_path):
    root = _root(tmp_path)
    bad = [None, {"ok": False}, {"ok": True, "prefs": None}, {"ok": True, "prefs": {**PREFS, "v": 2}},
           {"ok": True, "prefs": {**PREFS, "weights": {"nope": 1}}}, {"ok": True, "prefs": {**PREFS, "weights": {"economy": 9}}},
           {"ok": True, "prefs": {**PREFS, "weights": {"economy": True}}}, {"ok": True, "prefs": {**PREFS, "keywords": ["x" * 31]}}]
    for b in bad:
        r = learned.learn(root, date(2026, 10, 26), RC, lambda rc, b=b: b)
        assert r["status"].startswith("건너뜀"), b
    assert learned.learn(root, date(2026, 10, 26), None, _ok())["status"].startswith("건너뜀: 중계 서버")

    def boom(rc):
        raise OSError("down")
    assert "받기 실패" in learned.learn(root, date(2026, 10, 26), RC, boom)["status"]
    assert not learned.learned_path(root).exists()


def test_overlay_weights_less_keywords(tmp_path):
    root = _root(tmp_path)
    plain = load_interests(root)
    assert plain.learned_week is None and plain.base_weights == build_interest_table(load_interests(root, learned=False)).topic_weights
    learned.learn(root, date(2026, 10, 26), RC, _ok())
    i = load_interests(root)
    t = build_interest_table(i).topic_weights
    base = build_interest_table(load_interests(root, learned=False)).topic_weights
    assert t["economy"] == 2.5 and t["incidents"] == 0.0 and t["science"] == 1.2
    assert t["politics"] == base["politics"] and t["industry"] == base["industry"]   # 학습값 없는 분야는 그대로
    assert "incidents" in i.less and "economy" not in i.less and "science" not in i.less
    assert set(i.less) == {k for k in TOPICS if t[k] < i.default_weight}
    assert i.keywords == ["원전", "HBM"] and i.learned_week == "2026-W44" and i.base_weights == base
    assert i.base_keywords == load_interests(root, learned=False).keywords


def test_broken_learned_file_falls_back(tmp_path):
    root = _root(tmp_path)
    p = learned.learned_path(root)
    p.parent.mkdir(parents=True)
    p.write_text("{ broken", encoding="utf-8")
    assert load_interests(root).topics == load_interests(root, learned=False).topics


def test_worker_topics_match_pipeline():
    src = (ROOT / "worker" / "src" / "prefs.js").read_text(encoding="utf-8")
    js = re.findall(r'"(\w+)"', re.search(r"TOPICS = \[(.*?)\]", src, re.S).group(1))
    assert js == list(TOPICS)


def test_fetch_known_concepts():
    """S31a: 발행마다 /prefs 에서 아는 경제 개념만. 실패·형식 오류·없음이면 []."""
    ok = {"ok": True, "prefs": {**PREFS, "known": [" 기준금리와 환율 ", "기준금리와 환율", "밸류에이션"]}}
    assert learned.fetch_known(RC, lambda rc: ok) == ["기준금리와 환율", "밸류에이션"]
    assert learned.fetch_known(None, lambda rc: ok) == []
    for bad in [None, {"ok": False}, {"ok": True, "prefs": None}, {"ok": True, "prefs": {**PREFS, "known": "x"}},
                {"ok": True, "prefs": {**PREFS, "known": ["가" * 41]}}, {"ok": True, "prefs": PREFS}]:
        assert learned.fetch_known(RC, lambda rc, b=bad: b) == [], bad

    def boom(rc):
        raise OSError("down")
    assert learned.fetch_known(RC, boom) == []
    assert learned.clean({**PREFS, "known": ["가"] * 101}) is None   # 주간 반영 값도 같은 규칙
