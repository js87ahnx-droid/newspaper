"""S38c 편집 리뷰 받기와 주간 자동 조정.

기준 (project-plan.md S38c):
- 받은 리뷰를 메모 없이 data/reviews 에
- 10건 미만·같은 주에는 다시 바꾸지 않음
- 위로 받은 기사가 중요도 높은 쪽이면 중요도 가중치가 오름 (가짜 리뷰)
- 상·하한, 되돌리기, load_config 가 덮어 읽음 (저장소 테스트는 학습값 없이)
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from pipeline import review
from pipeline.settings import ROOT, TOPICS, load_config

BASE = load_config(learned=False)
RC = {"url": "https://reader.test", "key": "k"}
D = date(2026, 11, 3)   # 화요일, 2026-W45


def item(verdict, imp=0.5, att=0.5, head=0.0, cont=0.0, topic="economy", memo=None, section="economy", rank=1):
    r = {"verdict": verdict, "topic": topic, "section": section, "rank": rank,
         "scores": {"attention": att, "importance": imp, "headline": head, "continuity": cont, "interest": 0.3, "final": 0.5}}
    if memo:
        r["memo"] = memo
    return r


def rec(day, items):
    return {"v": 1, "edition": day, "items": items, "updated": day + "T09:00:00Z"}


def fetcher(records, reset=None, calls=None):
    def f(rc, since):
        if calls is not None:
            calls.append(since)
        return {"ok": True, "reviews": records, "reset": reset}
    return f


def mixed(n_up=6, n_down=6, day="2026-11-02"):
    """중요도 높은 기사는 위로, 낮은 기사는 아래로."""
    items = {f"u{i}": item("up", imp=0.9, topic="politics") for i in range(n_up)}
    items.update({f"d{i}": item("down", imp=0.2, topic="entertainment_sports", memo="비밀 메모") for i in range(n_down)})
    return rec(day, items)


def test_saved_without_memo(tmp_path):
    r = review.learn(tmp_path, D, RC, BASE, fetcher([mixed()]))
    f = tmp_path / "data" / "reviews" / "2026-11-02.json"
    text = f.read_text(encoding="utf-8")
    assert "memo" not in text and "비밀 메모" not in text
    saved = json.loads(text)
    assert saved["items"]["u0"]["verdict"] == "up" and r["saved"] == 1
    # 같은 것을 다시 받으면 파일을 다시 쓰지 않는다
    assert review.learn(tmp_path, D + timedelta(days=1), RC, BASE, fetcher([mixed()]))["saved"] == 0


def test_bad_records_skipped(tmp_path):
    bad = [rec("2026-11-02", {"x": {"verdict": "great"}}), {"v": 2}, rec("../evil", {}), rec("2026-11-01", {"../a": item("up")})]
    review.learn(tmp_path, D, RC, BASE, fetcher(bad))
    assert not (tmp_path / "data" / "reviews").exists() or list((tmp_path / "data" / "reviews").glob("*")) == []


def test_too_few_no_change(tmp_path):
    r = review.learn(tmp_path, D, RC, BASE, fetcher([mixed(4, 5)]))
    assert r["status"].startswith("리뷰 부족") and "9/10" in r["status"]
    assert not review.learned_path(tmp_path).exists()


def test_importance_weight_rises(tmp_path):
    r = review.learn(tmp_path, D, RC, BASE, fetcher([mixed()]))
    assert r["status"] == "조정"
    got = json.loads(review.learned_path(tmp_path).read_text(encoding="utf-8"))
    assert got["week"] == "2026-W45" and got["reviews"] == 12
    assert got["weights"]["importance"] > BASE.weights.importance
    assert got["weights"]["attention"] == pytest.approx(BASE.weights.attention)   # 차이 없는 지표는 그대로
    assert got["topic_importance"]["politics"] > BASE.importance.topic_weights["politics"]
    assert got["topic_importance"]["entertainment_sports"] < BASE.importance.topic_weights["entertainment_sports"]
    assert {c["key"] for c in got["changes"]} >= {"importance", "politics", "entertainment_sports"}
    assert "interest" not in got["weights"]                                       # 관심도 가중치는 손대지 않음
    cfg = load_config(tmp_path_root(tmp_path))
    assert cfg.weights.importance == got["weights"]["importance"]
    assert cfg.importance.topic_weights["politics"] == got["topic_importance"]["politics"]


def tmp_path_root(tmp_path):
    """load_config 가 tmp 루트에서 config.yaml 을 읽도록 복사."""
    (tmp_path / "config.yaml").write_bytes((ROOT / "config.yaml").read_bytes())
    return tmp_path


def test_same_week_once(tmp_path):
    review.learn(tmp_path, D, RC, BASE, fetcher([mixed()]))
    first = review.learned_path(tmp_path).read_text(encoding="utf-8")
    r = review.learn(tmp_path, D + timedelta(days=2), RC, BASE, fetcher([mixed(), mixed(day="2026-11-04")]))
    assert r["status"] == "이번 주 이미 조정"
    assert review.learned_path(tmp_path).read_text(encoding="utf-8") == first
    r = review.learn(tmp_path, D + timedelta(days=6), RC, BASE, fetcher([mixed()]))   # 다음 주(W46)
    assert r["status"] == "조정"


def test_bounds(tmp_path):
    """같은 쪽으로 20주 밀어도 config 값의 0.7~1.3배(가중치), 0.6~1.4배(분야) 안."""
    for k in range(20):
        day = D + timedelta(weeks=k)
        review.learn(tmp_path, day, RC, BASE, fetcher([mixed(day=(day - timedelta(days=1)).isoformat())]))
    got = json.loads(review.learned_path(tmp_path).read_text(encoding="utf-8"))
    assert got["weights"]["importance"] == pytest.approx(BASE.weights.importance * 1.3)
    assert got["topic_importance"]["politics"] == pytest.approx(BASE.importance.topic_weights["politics"] * 1.4)
    assert got["topic_importance"]["entertainment_sports"] == pytest.approx(BASE.importance.topic_weights["entertainment_sports"] * 0.6)
    for k, v in got["weights"].items():
        assert getattr(BASE.weights, k) * 0.7 - 1e-9 <= v <= getattr(BASE.weights, k) * 1.3 + 1e-9
    assert len(got["history"]) == review.HISTORY_KEEP


def test_reset(tmp_path):
    review.learn(tmp_path, D, RC, BASE, fetcher([mixed()]))
    r = review.learn(tmp_path, D + timedelta(days=1), RC, BASE, fetcher([mixed()], reset="2026-11-04T01:00:00.000Z"))
    assert r["status"].startswith("되돌림")
    got = json.loads(review.learned_path(tmp_path).read_text(encoding="utf-8"))
    assert "weights" not in got and got["since"] == "2026-11-04"
    cfg = load_config(tmp_path_root(tmp_path))
    assert cfg.weights.importance == BASE.weights.importance
    # 같은 되돌리기 시각은 다시 보지 않고, 되돌린 날 이전 호 리뷰는 쓰지 않는다
    r = review.learn(tmp_path, D + timedelta(days=7), RC, BASE, fetcher([mixed()], reset="2026-11-04T01:00:00.000Z"))
    assert r["status"].startswith("리뷰 부족")
    r = review.learn(tmp_path, D + timedelta(days=7), RC, BASE, fetcher([mixed(day="2026-11-09")], reset="2026-11-04T01:00:00.000Z"))
    assert r["status"] == "조정"


def test_fetch_failure_and_no_server(tmp_path):
    def boom(rc, since):
        raise OSError("down")
    assert review.learn(tmp_path, D, RC, BASE, boom)["status"].startswith("건너뜀: 받기 실패")
    assert review.learn(tmp_path, D, None, BASE, boom)["status"].startswith("건너뜀")
    assert review.learn(tmp_path, D, RC, BASE, lambda rc, s: {"ok": False})["status"].startswith("건너뜀")


def test_window_28_days(tmp_path):
    calls = []
    review.learn(tmp_path, D, RC, BASE, fetcher([mixed(day="2026-10-01")], calls=calls))
    assert calls == ["2026-10-06"]
    assert review.learn(tmp_path, D + timedelta(days=7), RC, BASE, fetcher([]))["status"].startswith("리뷰 부족")


def test_repo_tests_ignore_committed_learned():
    assert review.learned_path(ROOT).name == "_no-editing-learned.json"
    assert load_config().weights == BASE.weights


def test_random_reviews_do_not_drift():
    """한쪽으로 쏠림 없는 무작위 리뷰 4주치 (S38e): 가중치가 ±5% 넘게 움직이지 않는다."""
    rnd = random.Random(7)
    base_w = {k: getattr(BASE.weights, k) for k in review.TUNED}
    base_t = dict(BASE.importance.topic_weights)
    cur_w, cur_t = dict(base_w), dict(base_t)
    for _ in range(4):
        rs = [{"verdict": rnd.choice(["ok", "up", "down", "drop", "ok"]), "topic": rnd.choice(list(TOPICS)),
               "scores": {k: rnd.random() for k in review.SCORE_KEYS}} for _ in range(60)]
        cur_w, cur_t, _ = review.adjust(rs, base_w, cur_w, base_t, cur_t)
    for k in review.TUNED:
        assert abs(cur_w[k] / base_w[k] - 1) < 0.05, (k, cur_w[k])


def test_overlay_ignores_bad_values():
    cfg = review.overlay(BASE, {"weights": {"importance": "x", "attention": -1, "interest": 9, "headline": 0.3},
                                "topic_importance": {"nope": 1, "politics": True}})
    assert cfg.weights.headline == 0.3 and cfg.weights.importance == BASE.weights.importance
    assert cfg.weights.interest == BASE.weights.interest
    assert cfg.importance.topic_weights == BASE.importance.topic_weights


def test_learn_cli_runs_without_server(tmp_path, monkeypatch, capsys):
    from pipeline.__main__ import main
    monkeypatch.delenv("READER_URL", raising=False)
    monkeypatch.delenv("READER_KEY", raising=False)
    root = tmp_path_root(tmp_path)
    for f in ("sources.yaml", "interests.yaml"):
        (root / f).write_bytes((ROOT / f).read_bytes())
    assert main(["--root", str(root), "learn", "--date", D.isoformat()]) == 0
    assert "편집 리뷰: 건너뜀" in capsys.readouterr().out
    assert not Path(root / "data" / "reviews").exists()
