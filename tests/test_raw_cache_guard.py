"""S35: 누적분 캐시를 못 불러온 실행이 빈 누적분을 저장하지 않게 (scripts/raw_cache_guard.sh, 워크플로 연결)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "raw_cache_guard.sh"
BASH = shutil.which("bash")


def run_guard(tmp_path, matched, strict, gh):
    """gh 를 흉내 내는 스크립트를 PATH 앞에 두고 돌린다. gh=None 이면 gh 가 실패한다."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "gh"
    fake.write_text("#!/usr/bin/env bash\n" + (f"echo {gh}\n" if gh is not None else "exit 1\n"), newline="\n")
    fake.chmod(0o755)
    out = tmp_path / "out.txt"
    env = {**os.environ, "GITHUB_OUTPUT": str(out), "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    args = [BASH, str(SCRIPT), matched] + ([strict] if strict else [])
    p = subprocess.run(args, env=env, capture_output=True, text=True, encoding="utf-8")
    return p.returncode, out.read_text(encoding="utf-8").strip() if out.exists() else ""


@pytest.mark.skipif(BASH is None, reason="bash 없음")
@pytest.mark.parametrize("matched,strict,gh,code,save", [
    ("raw-123", "1", "1", 0, "save=true"),     # 불러옴
    ("", "1", "0", 0, "save=true"),            # 누적분이 처음부터 없음 → 쌓기 시작
    ("", "1", "1", 1, "save=false"),           # 불러오기 실패 (10/31) → 수집은 실패로
    ("", "", "1", 0, "save=false"),            # 발행은 계속하되 저장 안 함
    ("", "1", None, 1, "save=false"),          # 확인을 못 하면 실패로 본다
])
def test_guard(tmp_path, matched, strict, gh, code, save):
    assert run_guard(tmp_path, matched, strict, gh) == (code, save)


def _steps(name):
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
    job = next(iter(j for k, j in wf["jobs"].items() if k != "check"))
    return wf, {s.get("name"): s for s in job["steps"]}


@pytest.mark.parametrize("name,strict", [("collect.yml", True), ("daily.yml", False)])
def test_workflow_saves_only_after_good_restore(name, strict):
    wf, steps = _steps(name)
    restore = steps["누적분 불러오기"]
    guard = next(s for s in steps.values() if s.get("id") == "rawguard")
    assert restore["id"] == "raw"
    assert "steps.raw.outputs.cache-matched-key" in guard["run"]
    assert guard["run"].rstrip().endswith(" 1") == strict
    assert "steps.rawguard.outputs.save == 'true'" in steps["누적분 저장"]["if"]
    assert wf["permissions"].get("actions") in ("read", "write")


def test_collect_gets_model_from_hf_first():
    _, steps = _steps("collect.yml")
    names = list(steps)
    hf = next(s for s in steps.values() if s.get("id") == "hf")
    cache = steps["임베딩 모델 캐시 (HF 실패 때만)"]
    assert hf["continue-on-error"] is True
    assert cache["uses"].startswith("actions/cache/restore@") and "failure" in cache["if"]
    assert names.index(cache["name"]) < names.index("수집·임베딩")
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8"))
    setup = next(s for s in wf["jobs"]["collect"]["steps"] if str(s.get("uses", "")).startswith("actions/setup-python"))
    assert "cache" not in setup["with"]   # pip 캐시도 쓰지 않는다
