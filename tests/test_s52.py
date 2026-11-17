"""S52 발행 진행 상황: scripts/run_status.py 와 발행 흐름 연결."""
from __future__ import annotations

import base64
import io
import json
import re
import subprocess
import urllib.error
from pathlib import Path

import pytest

import scripts.run_status as rs

ROOT = Path(__file__).resolve().parent.parent


# ---------- 오류 한 줄 ----------
def test_extract_error_order():
    log = "시작\n::error::NEWS_PASSWORD 가 없습니다.\nTraceback\nKeyError: 'lead'\n끝"
    assert rs.extract_error([log]) == "NEWS_PASSWORD 가 없습니다."               # ::error 가 먼저
    assert rs.extract_error(["a\nTraceback (most recent call last):\n  x\nKeyError: 'lead'\n마지막"]) == "KeyError: 'lead'"
    assert rs.extract_error(["a\n\nexit 1\n\n"]) == "exit 1"
    assert rs.extract_error(["", ""]) == ""


def test_extract_error_push_title_and_push_log_first():
    push = "::error title=발행 push 실패 (충돌)::발행 결과를 push 하지 못함 — 다른 커밋"
    assert rs.extract_error([push, "::error::다른 것"]) == "발행 결과를 push 하지 못함 — 다른 커밋"
    assert rs.extract_error(["", "::error::daily 쪽"]) == "daily 쪽"                # push.log 가 비면 daily.log


def test_extract_error_hides_article_like_exception_message():
    assert rs.extract_error(["ValueError: 수능 이틀 앞 AI 커닝 기사 제목"]) == "ValueError"
    assert rs.extract_error(["KeyError: 'Trump says tariffs will stay'"]) == "KeyError"            # 로마자 문장꼴 (2차 M8)
    assert rs.extract_error(["RuntimeError: bad json"]) == "RuntimeError: bad json"
    assert rs.extract_error(["HTTPError: 404 for https://news.example.com/2026/headline-slug"]) == "HTTPError: 404 for <주소>"
    assert rs.scrub("::x https://a.example/b?k=1", [], []) == "::x <주소>"


def test_scrub_secrets_samples_and_length():
    env = {"NEWS_PASSWORD": "pw-1234", "READER_URL": "https://reader.example.dev/x", "READER_KEY": "rk-zzzz"}
    sec = rs.secret_values(env)
    out = rs.scrub("ConnectionError: HTTPSConnectionPool(host='reader.example.dev') key=rk-zzzz pw-1234 sk-ant-abcdefghijklmn", sec, [])
    assert "reader.example.dev" not in out and "rk-zzzz" not in out and "pw-1234" not in out and "sk-ant" not in out
    sample = ["Netanyahu faces new corruption charges in court"]
    assert rs.scrub("KeyError: Netanyahu faces new corr", [], sample) == "KeyError — (기사 글이 들어 있어 생략)"   # 조각도 잡는다
    assert rs.scrub("기사 글이 평문으로 있음: docs/x — 예: Netanyahu faces", [], sample) == "(기사 글이 들어 있어 생략)"
    assert len(rs.scrub("x" * 500, [], [])) == rs.MAX


def test_article_samples_like_verify_site(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "ROOT", tmp_path)
    (tmp_path / "data" / "raw").mkdir(parents=True)
    ed = {"sections": {"politics": [{"title": "정치 기사 제목 열 글자 넘게", "lead": "리" * 40}, {"title": "짧음"}]},
          "opinion": {"editorials": [{"title": "사설 제목도 여덟 자 넘게"}]}}
    (tmp_path / "data" / "raw" / "2026-11-18.edition.json").write_text(json.dumps(ed, ensure_ascii=False), encoding="utf-8")
    assert rs.article_samples("2026-11-18") == ["정치 기사 제목 열 글자 넘게", "리" * 30, "사설 제목도 여덟 자 넘게"]
    assert rs.article_samples("2026-11-19") == []


# ---------- 올리기 ----------
class _Resp(io.BytesIO):
    def __init__(self, body=b"{}", status=200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(calls, get=None, put_codes=(201,)):
    codes = list(put_codes)

    def op(req, timeout=None):
        calls.append(req)
        if req.get_method() == "GET":
            if get is None:
                raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
            return _Resp(json.dumps(get).encode())
        c = codes.pop(0) if codes else 201
        if c >= 400:
            raise urllib.error.HTTPError(req.full_url, c, "x", {}, None)
        return _Resp(b"{}", c)
    return op


ENV = {"STATUS_TOKEN": "t0ken-abc", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "9"}


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(rs, "STEP_FILE", tmp_path / "run" / "status-step.json")
    monkeypatch.setattr(rs, "LOGS", [tmp_path / "run" / "push.log", tmp_path / "run" / "daily.log"])
    monkeypatch.setattr(rs, "ROOT", tmp_path)
    return tmp_path / "run"


def _body(req):
    d = json.loads(req.data)
    return d, json.loads(base64.b64decode(d["content"]))


def test_no_token_no_call(run_dir):
    calls = []
    assert rs.cmd_set("2026-11-18", 1, env={}, opener=_opener(calls)) == "토큰 없음 — 올리지 않음" and not calls
    assert json.loads(rs.STEP_FILE.read_text(encoding="utf-8"))["step"] == 1


def test_set_put_with_sha_and_payload(run_dir):
    calls = []
    rs.cmd_set("2026-11-18", 1, env=ENV, opener=_opener(calls))
    out = rs.cmd_set("2026-11-18", 4, env=ENV, opener=_opener(calls, get={"sha": "abc"}))
    assert out.startswith("올림")
    d, body = _body(calls[-1])
    assert d["sha"] == "abc" and d["branch"] == "main" and d["message"].startswith("상태: 2026-11-18 running 4/7")
    assert body["state"] == "running" and body["step"] == 4 and body["steps"] == 7 and body["label"] == "AI 요약·분석"
    assert body["run"].endswith("/o/r/actions/runs/9") and body["started"] and body["updated"]
    assert "t0ken" not in json.dumps(body)
    assert calls[-1].full_url == "https://api.github.com/repos/o/r/contents/docs/status.json"


def test_set_other_date_or_without_start_is_skipped(run_dir):
    calls = []
    assert "건너뜀" in rs.cmd_set("2026-11-18", 3, env=ENV, opener=_opener(calls)) and not calls   # 단계 1 없이
    rs.cmd_set("2026-11-18", 1, env=ENV, opener=_opener(calls))
    n = len(calls)
    assert "건너뜀" in rs.cmd_set("2026-11-17", 7, env=ENV, opener=_opener(calls)) and len(calls) == n
    assert "건너뜀" in rs.cmd_done("2026-11-17", env=ENV, opener=_opener(calls)) and len(calls) == n
    assert "건너뜀" in rs.cmd_set("", 1, env=ENV, opener=_opener(calls))
    rs.cmd_done("2026-11-18", env=ENV, opener=_opener(calls))
    assert _body(calls[-1])[1]["state"] == "done"


def test_api_errors_never_raise(run_dir):
    calls = []
    assert rs.cmd_set("2026-11-18", 1, env=ENV, opener=_opener(calls, put_codes=(409, 201))).startswith("올림")   # sha 엇갈림 → 한 번 더
    assert rs.cmd_set("2026-11-18", 2, env=ENV, opener=_opener(calls, put_codes=(500,))) == "못 올림 (HTTP 500)"

    def boom(req, timeout=None):
        raise OSError("net")
    assert rs.cmd_set("2026-11-18", 2, env=ENV, opener=boom) == "못 올림 (OSError)"


def test_fail_uses_step_and_log(run_dir):
    calls = []
    rs.cmd_set("2026-11-18", 1, env=ENV, opener=_opener(calls))
    rs.cmd_set("2026-11-18", 5, env=ENV, opener=_opener(calls))
    (run_dir / "daily.log").write_text("…\nKeyError: 'lead'\n", encoding="utf-8")
    rs.cmd_fail(False, env={**ENV, "NEWS_PASSWORD": "lead"}, opener=_opener(calls))
    body = _body(calls[-1])[1]
    assert body["state"] == "error" and body["step"] == 5 and body["label"] == "지면 만들기"
    assert body["message"] == "KeyError: '***'"                                    # 비밀값과 같은 글자도 지움
    rs.cmd_fail(True, env=ENV, opener=_opener(calls))
    assert _body(calls[-1])[1]["message"].startswith("실행이 취소됐거나 시간이 초과됨")


def test_fail_without_step_file_uses_edition_date(run_dir):
    calls = []
    rs.cmd_fail(False, env={**ENV, "EDITION_DATE": "2026-11-20"}, opener=_opener(calls))
    body = _body(calls[-1])[1]
    assert body["date"] == "2026-11-20" and body["step"] == 1 and body["message"] == rs.NO_LOG     # daily.sh 전(설치·캐시) 실패
    run_dir.mkdir(exist_ok=True)
    (run_dir / "daily.log").write_text("", encoding="utf-8")
    rs.cmd_fail(False, env=ENV, opener=_opener(calls))
    assert _body(calls[-1])[1]["message"] == "오류 문장 없음 (Actions 로그 확인)"
    assert re.fullmatch(r"\d{4}-\d\d-\d\d", rs.fallback_date({}))


def test_main_never_fails(run_dir, monkeypatch):
    monkeypatch.setattr(rs, "cmd_set", lambda *a, **k: 1 / 0)
    assert rs.main(["set", "2026-11-18", "1"]) == 0
    assert rs.main(["모름"]) == 0


# ---------- 발행 흐름 연결 (S52b) ----------
DAILY = (ROOT / "scripts" / "daily.sh").read_text(encoding="utf-8")
WF = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")


def test_daily_sh_steps_in_order():
    body = DAILY.split("echo \"date=$DATE\"", 1)[1]
    steps = [int(m) for m in re.findall(r"^\s*status (\d)\b", body, re.M)]
    assert steps == [1, 5, 2, 3, 4, 5, 6], steps                                     # render_only 갈래(5) → 전체 갈래(2·3·4·5) → 6
    i_skip, i_one, i_pw = body.index("SKIP_IF_PUBLISHED"), body.index("status 1"), body.index("NEWS_PASSWORD:-")
    assert i_skip < i_one < i_pw                                                     # 이미 발행이면 안 올림, 비밀번호 없음은 단계 1 오류
    assert "unset STATUS_TOKEN" in DAILY
    assert not re.search(r"(>|cp|mv|tee)\s+\S*docs/status\.json", DAILY)          # 로컬 docs 에 쓰지 않는다 (발행 커밋에 안 섞임)


def test_daily_sh_token_not_exported(tmp_path):
    """STATUS_TOKEN 은 daily.sh 안의 다른 프로세스(claude CLI 등)에 넘어가지 않는다."""
    head = DAILY.split("PY=", 1)[0]
    i = DAILY.index("_STATUS_TOKEN=")
    snippet = DAILY[i:DAILY.index("\n", DAILY.index("unset STATUS_TOKEN"))]
    script = tmp_path / "t.sh"
    script.write_text("set -euo pipefail\n" + snippet + "\nenv | grep -c STATUS_TOKEN || true\necho \"in-shell=${_STATUS_TOKEN}\"\n", encoding="utf-8")
    out = subprocess.run(["bash", str(script)], env={"STATUS_TOKEN": "abc", "PATH": __import__("os").environ["PATH"]},
                         capture_output=True, text=True).stdout
    assert out.split()[0] == "0" and "in-shell=abc" in out, (head[:0], out)


def test_workflow_pipefail_and_status_steps():
    pub = WF.split("- name: 발행\n", 1)[1].split("- name:", 1)[0]
    push = WF.split("- name: 커밋·푸시", 1)[1].split("- name:", 1)[0]
    assert "set -o pipefail" in pub and "| tee data/run/daily.log" in pub and "STATUS_TOKEN: ${{ github.token }}" in pub
    assert "set -o pipefail" in push and "| tee data/run/push.log" in push and "run_status.py set \"$EDITION\" 7 || true" in push
    assert "unset STATUS_TOKEN_IN" in push and "STATUS_TOKEN:" not in push                     # 토큰은 상태 호출에만
    assert "GH_TOKEN" not in pub
    fail = WF.split("- name: 발행 상태 — 실패", 1)[1].split("- name:", 1)[0]
    assert "(failure() || cancelled())" in fail and "steps.push.outputs.result" in fail and "run_status.py fail" in fail
    for k in ("NEWS_PASSWORD", "READER_URL", "READER_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        assert f"{k}: ${{{{ secrets.{k} }}}}" in fail
    done = WF.split("- name: 발행 상태 — 끝", 1)[1].split("- name:", 1)[0]
    assert "run_status.py done \"$EDITION\" || true" in done and "pushed" in done and "run_status.py fail $IS_CANCELLED || true" in fail


def test_tee_pipe_keeps_exit_code(tmp_path):
    """B1: pipefail 이 있으면 tee 를 거쳐도 실패 종료 코드가 이어진다."""
    log = tmp_path / "x.log"
    r = subprocess.run(["bash", "-e", "-c", f"set -o pipefail\nbash -c 'echo hi; exit 3' 2>&1 | tee '{log.as_posix()}'"], capture_output=True)
    assert r.returncode == 3 and log.read_text().strip() == "hi"


def test_gitignore_run_dir():
    assert "data/run/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_short_steps_recorded_not_posted(run_dir):
    calls = []
    rs.cmd_set("2026-11-18", 1, env=ENV, opener=_opener(calls))
    n = len(calls)
    for st in (6, 7):
        assert rs.cmd_set("2026-11-18", st, env=ENV, opener=_opener(calls)) == "기록만 (짧은 단계)" and len(calls) == n
        assert json.loads(rs.STEP_FILE.read_text(encoding="utf-8"))["step"] == st              # 오류 때 이 단계로
    rs.cmd_fail(False, env=ENV, opener=_opener(calls))
    assert _body(calls[-1])[1]["step"] == 7


def test_step_file_written_even_if_post_fails(run_dir):
    def boom(req, timeout=None):
        raise OSError("net")
    rs.cmd_set("2026-11-18", 1, env=ENV, opener=boom)
    calls = []
    assert rs.cmd_set("2026-11-18", 3, env=ENV, opener=_opener(calls)).startswith("올림")      # 단계 1 이 못 올라가도 다음 단계는 올림


def test_fail_skips_already_published_without_start(run_dir, tmp_path):
    (tmp_path / "docs" / "archive" / "2026-11-18").mkdir(parents=True)
    (tmp_path / "docs" / "archive" / "2026-11-18" / "index.html").write_text("x", encoding="utf-8")
    calls = []
    assert "건너뜀" in rs.cmd_fail(False, env={**ENV, "EDITION_DATE": "2026-11-18"}, opener=_opener(calls)) and not calls


def test_last_line_with_text_hidden():
    nl = chr(10)
    assert rs.extract_error(["1면: 수능 이틀 앞 AI 커닝" + nl + "Killed"]) == "Killed"
    assert rs.extract_error(["x" + nl + "1면: 수능 이틀 앞 AI 커닝"]) == rs.LAST_HIDDEN
    assert rs.extract_error(["x" + nl + "Trump says tariffs will stay"]) == rs.LAST_HIDDEN
    assert rs.extract_error(["x" + nl + "exit 137"]) == "exit 137"


def test_newer_running_or_error_not_overwritten(run_dir):
    calls = []
    newer = {"sha": "s", "content": base64.b64encode(json.dumps({"date": "2026-11-19", "state": "error"}).encode()).decode()}
    rs.cmd_set("2026-11-10", 1, env=ENV, opener=_opener(calls, get=newer))
    assert all(c.get_method() == "GET" for c in calls)                                       # 옛 호 다시 만들기가 오늘 실패를 덮지 않음
    done_newer = {"sha": "s", "content": base64.b64encode(json.dumps({"date": "2026-11-19", "state": "done"}).encode()).decode()}
    assert rs.cmd_set("2026-11-10", 1, env=ENV, opener=_opener(calls, get=done_newer)).startswith("올림")
    older = {"sha": "s", "content": base64.b64encode(json.dumps({"date": "2026-11-09", "state": "running"}).encode()).decode()}
    assert rs.cmd_set("2026-11-10", 1, env=ENV, opener=_opener(calls, get=older)).startswith("올림")


def test_short_titles_and_three_word_names_hidden():
    assert rs.extract_error(["KeyError: 'Gaza truce collapses'"]) == "KeyError"                 # 낱말 3개 (구현 리뷰 M1)
    assert rs.scrub("x 9자짜리제목입니다 y", [], ["9자짜리제목입니다"]) == "(기사 글이 들어 있어 생략)"  # 10자 이하 표본은 통째로


def test_verify_site_status_json_only_warns(tmp_path):
    import sys
    docs = tmp_path / "docs"
    docs.mkdir()
    ed = tmp_path / "e.json"
    ed.write_text(json.dumps({"sections": {"x": [{"title": "Gaza truce collapses again"}]}}), encoding="utf-8")
    (docs / "status.json").write_text('{"message": "Gaza truce collapses again"}', encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "verify_site.py"), str(docs), str(ed)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and "::warning::" in r.stdout, r.stdout
    (docs / "other.txt").write_text("Gaza truce collapses again", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "verify_site.py"), str(docs), str(ed)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 1
