"""S61 발행 전 화면 — 상태 파일 최근 기록(recent)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import scripts.run_status as rs
from tests.test_s52 import ENV, _body, _opener, run_dir  # noqa: F401 (fixture)

ROOT = Path(__file__).resolve().parent.parent


def _remote(d):
    return {"sha": "s", "content": base64.b64encode(json.dumps(d).encode()).decode()}


def _start(date, iso):
    rs.write_step({"date": date, "step": 7, "started": iso})


def _row(date, h1, m1, h2, m2):
    return {"date": date, "started": f"{date}T{h1:02d}:{m1:02d}:00Z", "finished": f"{date}T{h2:02d}:{m2:02d}:00Z"}


def test_done_appends_recent_and_keeps_seven_by_date(run_dir):
    calls = []
    old = [_row(f"2026-11-{d:02d}", 21, 34, 22, 0) for d in range(10, 18)]   # 8개 (KST 06:34 시작이지만 날짜는 UTC 표기)
    _start("2026-11-26", "2026-11-25T21:34:00Z")                            # KST 11/26 06:34
    out = rs.cmd_done("2026-11-26", env=ENV, opener=_opener(calls, get=_remote({"date": "2026-11-26", "state": "running", "recent": old})))
    assert out.startswith("올림")
    rec = _body(calls[-1])[1]["recent"]
    assert [r["date"] for r in rec] == ["2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17", "2026-11-26"]
    assert rec[-1]["started"] == "2026-11-25T21:34:00Z" and rec[-1]["finished"]


def test_same_date_replaced(run_dir):
    calls = []
    _start("2026-11-26", "2026-11-25T20:34:00Z")                            # KST 05:34
    old = [{"date": "2026-11-26", "started": "2026-11-25T21:00:00Z", "finished": "2026-11-25T21:40:00Z"}]
    rs.cmd_done("2026-11-26", env=ENV, opener=_opener(calls, get=_remote({"date": "2026-11-26", "state": "running", "recent": old})))
    rec = _body(calls[-1])[1]["recent"]
    assert len(rec) == 1 and rec[0]["started"] == "2026-11-25T20:34:00Z"


def test_render_only_or_odd_time_not_added_but_kept(run_dir):
    old = [_row("2026-11-24", 21, 34, 22, 1)]
    for env, started in (({**ENV, "RENDER_ONLY": "1"}, "2026-11-25T21:34:00Z"),   # render_only
                         (ENV, "2026-11-26T06:20:00Z"),                           # KST 15:20 (수동 다시 만들기)
                         (ENV, "2026-11-25T19:50:00Z"),                           # KST 04:50
                         (ENV, "2026-11-27T21:34:00Z")):                          # 다른 날짜(옛 호 다시 만들기 = 시작 날짜 ≠ 호 날짜)
        calls = []
        _start("2026-11-26", started)
        rs.cmd_done("2026-11-26", env=env, opener=_opener(calls, get=_remote({"date": "2026-11-26", "state": "running", "recent": old})))
        assert _body(calls[-1])[1]["recent"] == old, (env, started)


def test_set_and_fail_carry_recent(run_dir):
    old = [_row("2026-11-24", 21, 34, 22, 1)]
    calls = []
    rs.cmd_set("2026-11-26", 1, env=ENV, opener=_opener(calls, get=_remote({"date": "2026-11-25", "state": "done", "recent": old})))
    assert _body(calls[-1])[1]["recent"] == old and _body(calls[-1])[1]["state"] == "running"
    calls = []
    rs.cmd_fail(False, env=ENV, opener=_opener(calls, get=_remote({"date": "2026-11-26", "state": "running", "recent": old})))
    assert _body(calls[-1])[1]["recent"] == old and _body(calls[-1])[1]["state"] == "error"


def test_missing_key_broken_or_404_starts_empty(run_dir):
    for get in (_remote({"date": "2026-11-25", "state": "done"}),                   # 키 없음 (배포 첫날, B1)
                {"sha": "s", "content": "@@not-base64"},                            # 깨짐
                _remote({"date": "2026-11-25", "state": "done", "recent": "x"}),    # 모양이 틀림
                _remote({"date": "2026-11-25", "state": "done", "recent": [{"date": 3}, {"date": "2026-11-20"}]}),
                None):                                                              # 404
        calls = []
        _start("2026-11-26", "2026-11-25T21:34:00Z")
        rs.cmd_done("2026-11-26", env=ENV, opener=_opener(calls, get=get))
        rec = _body(calls[-1])[1]["recent"]
        assert [r["date"] for r in rec] == ["2026-11-26"], get


def test_get_error_other_than_404_still_not_posted(run_dir):
    import urllib.error
    calls = []

    def op(req, timeout=None):
        calls.append(req)
        raise urllib.error.HTTPError(req.full_url, 500, "x", {}, None)
    _start("2026-11-26", "2026-11-25T21:34:00Z")
    assert rs.cmd_done("2026-11-26", env=ENV, opener=op).startswith("못 올림")
    assert all(c.get_method() == "GET" for c in calls)


def test_workflow_done_step_passes_render_only():
    wf = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    done = wf.split("- name: 발행 상태 — 끝", 1)[1].split("- name:", 1)[0]
    assert "RENDER_ONLY: ${{ inputs.render_only && '1' || '0' }}" in done
