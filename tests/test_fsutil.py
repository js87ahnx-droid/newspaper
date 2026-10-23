"""쓰다 끊긴 파일에 견디기 (S29d, 2026-10-23 로컬 실행이 끊기며 JSON·소스 파일이 NUL 바이트로 채워진 일)."""
import json
from datetime import date

from pipeline.collect import load_store
from pipeline.fsutil import read_json, write_atomic
from pipeline.llm import Budget
from pipeline.score import load_previous


def test_write_atomic_replaces_and_leaves_no_tmp(tmp_path):
    p = tmp_path / "a.json"
    write_atomic(p, '{"x": 1}')
    write_atomic(p, '{"x": 2}')
    assert json.loads(p.read_text(encoding="utf-8")) == {"x": 2} and not list(tmp_path.glob("*.tmp"))


def test_corrupt_files_are_skipped(tmp_path, capsys):
    nul = tmp_path / "bad.json"
    nul.write_bytes(b"\x00" * 64)
    assert read_json(nul, {"d": 1}) == {"d": 1} and "깨진 파일" in capsys.readouterr().err
    assert Budget(nul, date(2026, 10, 23), 50).used == 0
    hist = tmp_path / "history"
    hist.mkdir()
    (hist / "2026-10-22.json").write_bytes(b"\x00" * 10)
    (hist / "2026-10-21.json").write_text(json.dumps({"edition": "2026-10-21", "issues": [{"id": "x"}]}), encoding="utf-8")
    assert load_previous(hist, date(2026, 10, 23)) == (date(2026, 10, 21), [{"id": "x"}])
    store = tmp_path / "store.jsonl"
    store.write_text("\x00\x00\x00\n{broken\n", encoding="utf-8")
    assert load_store(store) == {}


def test_prune_raw_keeps_recent(tmp_path):
    from pipeline.__main__ import prune_raw
    for name in ["2026-10-01.json", "2026-10-01.edition.json", "2026-10-20.issues.json", "store.jsonl", "picks.json"]:
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "collect-log.jsonl").write_text(
        '{"collected_at": "2026-10-01T00:00:00+00:00"}\n{"collected_at": "2026-10-22T00:00:00+00:00"}\n', encoding="utf-8")
    assert prune_raw(tmp_path, date(2026, 10, 23)) == 2
    assert sorted(f.name for f in tmp_path.iterdir()) == ["2026-10-20.issues.json", "collect-log.jsonl", "picks.json", "store.jsonl"]
    assert (tmp_path / "collect-log.jsonl").read_text(encoding="utf-8").count("collected_at") == 1
