"""S39: 같은 호 중복 발행 막기 (scripts/push_edition.sh, 워크플로 연결).

11/5: 대기하던 #222 가 호출 시점 코드(옛 커밋)를 읽어 #221 이 올린 호를 다시 만들고 push 에서 충돌했다.
기준 (project-plan.md S39): 같은 호가 이미 있으면 덮어쓰지 않고 정상 종료, 다른 커밋은 rebase 해서 올림,
실패 원인 구분, 누적분은 푸시 뒤에 건너뛰지 않았을 때만, 기다린 뒤 최신 main 을 읽음, 날짜 계산.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "push_edition.sh"
BASH = shutil.which("bash")
GIT = shutil.which("git")
D = "2026-11-05"
INDEX = f"docs/archive/{D}/index.html"
needs_bash = pytest.mark.skipif(BASH is None or GIT is None, reason="bash·git 없음")


def git(cwd, *args):
    return subprocess.run([GIT, "-C", str(cwd), *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def put(repo, rel, text):
    f = Path(repo) / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8", newline="\n")


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


@pytest.fixture
def site(tmp_path):
    """원격(bare)과 발행 실행의 작업 사본 run, 그리고 다른 실행처럼 원격에 올리는 other."""
    remote = tmp_path / "remote.git"
    subprocess.run([GIT, "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    seed = tmp_path / "seed"
    subprocess.run([GIT, "clone", "-q", str(remote), str(seed)], check=True, capture_output=True)
    git(seed, "checkout", "-q", "-B", "main")
    put(seed, "docs/index.html", "어제 호\n")
    put(seed, "README.md", "처음\n")
    commit(seed, "시작")
    git(seed, "push", "-q", "origin", "main")
    run = tmp_path / "run"
    other = tmp_path / "other"
    for c in (run, other):
        subprocess.run([GIT, "clone", "-q", str(remote), str(c)], check=True, capture_output=True)
    return {"remote": remote, "run": run, "other": other, "tmp": tmp_path}


def push(site, force="0", fake_push=None):
    """스크립트 실행. fake_push: push 를 흉내 내는 bash 조각 (앞에서 정한 횟수만 실패 등)."""
    out, summary = site["tmp"] / "out.txt", site["tmp"] / "summary.md"
    out.write_text("", encoding="utf-8")
    env = {**os.environ, "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary), "PUSH_WAIT": "0"}
    if fake_push:
        bin_dir = site["tmp"] / "bin"
        bin_dir.mkdir(exist_ok=True)
        real = Path(GIT).as_posix()
        (bin_dir / "git").write_text(
            f'#!/usr/bin/env bash\nif [ "$1" = push ]; then\n{fake_push}\nfi\nexec "{real}" "$@"\n', encoding="utf-8", newline="\n")
        (bin_dir / "git").chmod(0o755)
        env["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    p = subprocess.run([BASH, str(SCRIPT), D, force], cwd=site["run"], env=env, capture_output=True, text=True, encoding="utf-8")
    return p.returncode, out.read_text(encoding="utf-8").strip(), p.stdout + p.stderr


def head(site):
    return git(site["remote"], "rev-parse", "main")


@needs_bash
def test_pushes_edition(site):
    put(site["run"], INDEX, "오늘 호\n")
    code, res, _ = push(site)
    assert (code, res) == (0, "result=pushed")
    assert git(site["remote"], "log", "-1", "--format=%s", "main") == f"발행: {D}"


@needs_bash
def test_nothing_changed(site):
    before = head(site)
    assert push(site)[:2] == (0, "result=nochange") and head(site) == before


@needs_bash
def test_same_edition_already_published_is_skipped(site):
    """11/5 #222: 옛 코드에서 만든 호 — 먼저 올라간 호를 덮어쓰지 않고 실패도 아니다."""
    put(site["other"], INDEX, "먼저 올린 호\n")
    commit(site["other"], f"발행: {D}")
    git(site["other"], "push", "-q", "origin", "main")
    first = head(site)
    put(site["run"], INDEX, "나중에 만든 호\n")
    code, res, log = push(site)
    assert (code, res) == (0, "result=skipped")
    assert head(site) == first
    assert git(site["remote"], "show", f"main:{INDEX}") == "먼저 올린 호"
    assert "::notice" in log and "이미 저장소에 있음" in log


@needs_bash
def test_other_commit_is_rebased(site):
    """발행 중 사용자가 코드를 올려도 호가 버려지지 않는다."""
    put(site["other"], "README.md", "코드 수정\n")
    commit(site["other"], "코드")
    git(site["other"], "push", "-q", "origin", "main")
    put(site["run"], INDEX, "오늘 호\n")
    assert push(site)[:2] == (0, "result=pushed")
    assert git(site["remote"], "show", "main:README.md") == "코드 수정"
    assert git(site["remote"], "show", f"main:{INDEX}") == "오늘 호"


@needs_bash
def test_force_replaces_own_edition(site):
    put(site["other"], INDEX, "지난 발행\n")
    commit(site["other"], f"발행: {D}")
    git(site["other"], "push", "-q", "origin", "main")
    git(site["run"], "pull", "-q", "origin", "main")
    put(site["run"], INDEX, "다시 만든 호\n")
    assert push(site, force="1")[:2] == (0, "result=pushed")
    assert git(site["remote"], "show", f"main:{INDEX}") == "다시 만든 호"


@needs_bash
def test_force_conflict_fails_without_overwriting(site):
    put(site["other"], "docs/index.html", "다른 실행의 호\n")
    commit(site["other"], "발행: 다른 호")
    git(site["other"], "push", "-q", "origin", "main")
    first = head(site)
    put(site["run"], "docs/index.html", "이 실행의 호\n")
    code, res, log = push(site, force="1")
    assert (code, res) == (1, "result=failed") and head(site) == first
    assert "발행 push 실패 (충돌)" in log and "docs/index.html" in log
    assert git(site["run"], "status", "--porcelain=2", "--branch").count("rebase") == 0


@needs_bash
def test_rejected_once_then_retried(site):
    counter = (site["tmp"] / "pushes").as_posix()
    put(site["run"], INDEX, "오늘 호\n")
    fake = (f'n=$(cat "{counter}" 2>/dev/null || echo 0); echo $((n+1)) > "{counter}"\n'
            'if [ "$n" = 0 ]; then echo "! [rejected] main -> main (fetch first)" >&2; exit 1; fi')
    assert push(site, fake_push=fake)[:2] == (0, "result=pushed")
    assert (site["tmp"] / "pushes").read_text().strip() == "2"


@needs_bash
@pytest.mark.parametrize("message,reason,tries", [
    ("remote: Permission to o/r.git denied to bot.\nfatal: unable to access: The requested URL returned error: 403", "권한", "1"),
    ("! [rejected] HEAD -> main (non-fast-forward)", "충돌", "3"),
    ("fatal: unable to access: Could not resolve host", "기타", "3"),
])
def test_failure_reason_in_annotation(site, message, reason, tries):
    counter = (site["tmp"] / "pushes").as_posix()
    put(site["run"], INDEX, "오늘 호\n")
    fake = f'n=$(cat "{counter}" 2>/dev/null || echo 0); echo $((n+1)) > "{counter}"\necho "{message}" >&2; exit 1'
    code, res, log = push(site, fake_push=fake)
    assert (code, res) == (1, "result=failed")
    assert f"::error title=발행 push 실패 ({reason})::" in log
    assert (site["tmp"] / "pushes").read_text().strip() == tries            # 권한은 다시 해도 안 된다
    assert f"push 실패 ({reason})" in (site["tmp"] / "summary.md").read_text(encoding="utf-8")


def _wf(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["daily.yml", "collect.yml"])
def test_reads_latest_main_after_waiting(name):
    """concurrency 로 기다린 실행도 호출 시점 커밋이 아니라 최신 main 을 읽는다. 같은 그룹, 진행 중인 실행은 취소하지 않음."""
    wf = _wf(name)
    assert wf["concurrency"] == {"group": "newspaper-data", "cancel-in-progress": False}
    for job in wf["jobs"].values():
        checkout = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
        assert checkout["with"]["ref"] == "main"


@pytest.mark.parametrize("name", ["daily.yml", "collect.yml"])
def test_edition_date_expression(name):
    """'5 hours 30 minutes ago' 는 GNU date 에서 4시간 30분 뒤다 ("ago" 가 바로 앞 단위에만 붙음). 자정~05:30 에 없는 호를 찾았다."""
    text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    assert "date -d '5 hours" not in text
    assert "date -d '330 minutes ago'" in text


@needs_bash
def test_330_minutes_ago_matches_current_edition():
    from datetime import datetime, timezone

    from pipeline.prepare import current_edition
    from pipeline.settings import load_config

    date = shutil.which("date")
    cfg = load_config(learned=False)
    for now, expect in [("2026-11-05 00:48", "2026-11-04"), ("2026-11-05 05:29", "2026-11-04"), ("2026-11-05 05:31", "2026-11-05"), ("2026-11-05 23:50", "2026-11-05")]:
        got = subprocess.run([date, "-d", f"{now} 330 minutes ago", "+%F"], env={**os.environ, "TZ": "UTC"}, capture_output=True, text=True).stdout.strip()
        kst = datetime.fromisoformat(now + "+09:00").astimezone(timezone.utc)
        assert got == expect == current_edition(kst, cfg).isoformat()


def test_raw_saved_after_push_unless_skipped():
    """누적분 저장은 푸시 뒤에. 같은 호를 건너뛰면 저장하지 않고, 발행·푸시 실패에는 지금처럼 저장 (S35a, AI 결과 재사용)."""
    steps = _wf("daily.yml")["jobs"]["publish"]["steps"]
    names = [s.get("name") for s in steps]
    assert names.index("발행") < names.index("커밋·푸시") < names.index("누적분 저장")
    pushed = steps[names.index("커밋·푸시")]
    assert pushed["id"] == "push" and "scripts/push_edition.sh" in pushed["run"]
    cond = steps[names.index("누적분 저장")]["if"]
    assert "always()" in cond and "steps.rawguard.outputs.save == 'true'" in cond
    assert "steps.push.outputs.result != 'skipped'" in cond


@needs_bash
def test_daily_skips_when_edition_on_latest_main(tmp_path):
    """발행 직전 재확인 (최신 main 을 읽으므로 먼저 올라간 호가 보인다). 호 날짜는 푸시 단계로 넘긴다."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "daily.sh", tmp_path / "scripts" / "daily.sh")
    put(tmp_path, INDEX, "먼저 올린 호\n")
    out = tmp_path / "out.txt"
    p = subprocess.run([BASH, str(tmp_path / "scripts" / "daily.sh")], capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "EDITION_DATE": D, "SKIP_IF_PUBLISHED": "1", "GITHUB_OUTPUT": str(out), "NEWS_PASSWORD": ""})
    assert p.returncode == 0 and "이미 발행된 호" in p.stdout
    assert f"date={D}" in out.read_text(encoding="utf-8")


def _dispatch_step(tmp_path, busy, published=False, hour="06", gh_fails=False):
    """collect.yml '아침 발행이 아직이면 daily 부르기' 단계를 가짜 gh·date 로 돌린다. 돌려주는 값: (gh workflow run 호출 여부, 출력)."""
    step = next(s for s in _wf("collect.yml")["jobs"]["collect"]["steps"] if s.get("name") == "아침 발행이 아직이면 daily 부르기")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "gh.log"
    list_out = "exit 1" if gh_fails else f"echo {busy}"
    (bin_ / "gh").write_text(f'#!/bin/sh\nif [ "$1 $2" = "run list" ]; then {list_out}; fi\n'
                             f'if [ "$1 $2" = "workflow run" ]; then echo called >> "{log.as_posix()}"; fi\n', encoding="utf-8")
    (bin_ / "date").write_text(f'#!/bin/sh\ncase "$*" in *%H*) echo {hour};; *) echo 2026-11-12;; esac\n', encoding="utf-8")
    for f in bin_.iterdir():
        f.chmod(0o755)
    if published:
        (tmp_path / "docs" / "archive" / "2026-11-12").mkdir(parents=True)
        (tmp_path / "docs" / "archive" / "2026-11-12" / "index.html").write_text("x", encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_.as_posix()}:{os.environ.get('PATH', '')}"}
    r = subprocess.run([BASH, "-e", "-c", step["run"]], cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return log.exists(), r.stdout


@needs_bash
@pytest.mark.parametrize("busy,published,hour,gh_fails,called", [
    (0, False, "06", False, True),    # 대기·진행 중인 daily 없음 → 부름
    (1, False, "06", False, False),   # 대기 중인 daily 있음 → 부르지 않음 (새로 부르면 그 실행이 취소됨, 11/11)
    (0, True, "06", False, False),    # 이미 발행됨
    (0, False, "13", False, False),   # 정오 지남
    (0, False, "06", True, True),     # 목록을 못 읽으면 그래도 부름 (발행을 놓치지 않게)
])
def test_collect_does_not_cancel_waiting_daily(tmp_path, busy, published, hour, gh_fails, called):
    """S44: 수집이 끝나며 daily 를 부를 때 이미 대기·진행 중인 daily 가 있으면 건너뛴다."""
    got, out = _dispatch_step(tmp_path, busy, published, hour, gh_fails)
    assert got == called, out


# S46: 아침 발행을 뉴욕 장 마감 + 30분 뒤로 (겨울 06:30, 여름 05:30 KST)
WAIT_PY = ROOT / "scripts" / "ny_close_wait.py"


def _wait(edition, now):
    r = subprocess.run([sys.executable, str(WAIT_PY), edition], env={**os.environ, "NOW": now},
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.parametrize("edition,now,expect", [
    ("2026-11-13", "2026-11-13T06:29:00+09:00", "wait 06:30"),   # 겨울, 뉴욕 11/12(목) 장 → 06:00 마감
    ("2026-11-13", "2026-11-13T06:31:00+09:00", "go"),
    ("2026-07-15", "2026-07-15T05:29:00+09:00", "wait 05:30"),   # 여름(서머타임) → 05:00 마감
    ("2026-07-15", "2026-07-15T05:31:00+09:00", "go"),
    ("2026-11-15", "2026-11-15T05:31:00+09:00", "go"),           # 일요일 호: 뉴욕 11/14 토요일 — 기다리지 않음
    ("2026-11-16", "2026-11-16T05:31:00+09:00", "go"),           # 월요일 호: 뉴욕 11/15 일요일
    ("2026-11-27", "2026-11-27T05:31:00+09:00", "go"),           # 뉴욕 11/26 추수감사절 휴장
    ("2026-11-10", "2026-11-11T01:40:00+09:00", "go"),           # 놓친 호를 다음 날 새벽에 — 호 날짜 기준이라 막지 않음
    ("2026-03-09", "2026-03-09T05:31:00+09:00", "go"),           # 3/8 서머타임 시작 뒤 첫 장(뉴욕 3/9 아님 — 3/8 일요일)
    ("2026-03-10", "2026-03-10T05:31:00+09:00", "go"),           # 뉴욕 3/9(월) 서머타임 → 05:00 마감
    ("2026-11-03", "2026-11-03T05:31:00+09:00", "wait 06:30"),   # 뉴욕 11/2(월) 표준시 (11/1 서머타임 끝)
])
def test_ny_close_wait(edition, now, expect):
    assert _wait(edition, now) == expect


def _check_step(tmp_path, now, edition_date="", skip_if_published="1", published=False):
    """daily.yml check 단계를 가짜 date·python3 로 돌린다. 돌려주는 값: (skip, 출력)."""
    job = _wf("daily.yml")["jobs"]["check"]
    step = next(s for s in job["steps"] if s.get("id") == "check")
    assert "pipeline" in job["steps"][0]["with"]["sparse-checkout"] and "scripts" in job["steps"][0]["with"]["sparse-checkout"]
    (tmp_path / "scripts").mkdir()
    shutil.copy(WAIT_PY, tmp_path / "scripts")
    shutil.copytree(ROOT / "pipeline", tmp_path / "pipeline", ignore=shutil.ignore_patterns("__pycache__"))
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "date").write_text("#!/bin/sh\necho 2026-11-13\n", encoding="utf-8")
    (bin_ / "python3").write_text(f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n', encoding="utf-8")
    for f in bin_.iterdir():
        f.chmod(0o755)
    if published:
        (tmp_path / "docs" / "archive" / "2026-11-13").mkdir(parents=True)
        (tmp_path / "docs" / "archive" / "2026-11-13" / "index.html").write_text("x", encoding="utf-8")
    out = tmp_path / "out.txt"
    env = {**os.environ, "PATH": f"{bin_.as_posix()}:{os.environ.get('PATH', '')}", "NOW": now, "GITHUB_OUTPUT": str(out),
           "EDITION_DATE": edition_date, "SKIP_IF_PUBLISHED": skip_if_published}
    r = subprocess.run([BASH, "-e", "-c", step["run"]], cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return out.read_text(encoding="utf-8").strip(), r.stdout


@needs_bash
@pytest.mark.parametrize("now,edition_date,skip_if_published,published,skip", [
    ("2026-11-13T05:33:00+09:00", "", "1", False, "skip=true"),            # 겨울 05:33 (Cloudflare 첫 호출) → 기다림
    ("2026-11-13T06:03:00+09:00", "", "1", False, "skip=true"),
    ("2026-11-13T06:33:00+09:00", "", "1", False, "skip=false"),           # 06:33 → 발행
    ("2026-11-13T06:33:00+09:00", "", "1", True, "skip=true"),             # 이미 발행됨
    ("2026-11-13T05:33:00+09:00", "2026-11-13", "1", False, "skip=false"),  # 날짜를 준 실행은 기다리지 않음
    ("2026-11-13T05:33:00+09:00", "", "0", False, "skip=false"),           # force 는 기다리지 않음
])
def test_daily_check_waits_for_ny_close(tmp_path, now, edition_date, skip_if_published, published, skip):
    got, out = _check_step(tmp_path, now, edition_date, skip_if_published, published)
    assert got == skip, out
