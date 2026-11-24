"""발행 진행 상황을 docs/status.json 에 올린다 (S52). 지난 호 목록이 이 파일을 읽어 "발행 중 / 발행 실패"를 띄운다.

표준 라이브러리만 쓴다 — 패키지 설치 전에 실패해도 오류를 올릴 수 있게.
GitHub Contents API 로 원격에만 커밋한다. 발행 작업의 checkout(docs/)은 건드리지 않아 마지막 발행 커밋과 부딪히지 않는다.
무엇이 실패해도 종료 코드는 0 — 상태 올리기 때문에 발행이 멈추면 안 된다.

사용
  python scripts/run_status.py set <호 날짜> <단계 1~7>   단계 1 이면 새 실행으로 시작, 2~7 은 단계 1 을 올린 같은 날짜일 때만
  python scripts/run_status.py done <호 날짜>             단계 1 을 올린 같은 날짜일 때만
  python scripts/run_status.py fail [--cancelled]         로그(data/run/push.log → daily.log)에서 오류 한 줄을 뽑아 error
환경변수
  STATUS_TOKEN        contents: write 토큰 (없으면 API 를 부르지 않는다 — 로컬 실행)
  GITHUB_REPOSITORY   소유자/저장소, STATUS_BRANCH (기본 main)
  GITHUB_SERVER_URL·GITHUB_RUN_ID  실행 주소
  EDITION_DATE        fail 때 단계 기록이 없으면 이 날짜
  RENDER_ONLY         "1" 이면 done 을 최근 기록(recent)에 넣지 않는다 (S61)
  NEWS_PASSWORD·READER_URL·READER_KEY·CLAUDE_CODE_OAUTH_TOKEN  오류 문장에서 이 값들을 지운다
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / "data" / "run"
STEP_FILE = RUN_DIR / "status-step.json"
LOGS = [RUN_DIR / "push.log", RUN_DIR / "daily.log"]
STEPS = ["시작", "수집", "편집", "AI 요약·분석", "지면 만들기", "암호화·검사", "올리기"]
PATH = "docs/status.json"
MAX = 200
SECRET_ENV = ("NEWS_PASSWORD", "READER_URL", "READER_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "STATUS_TOKEN", "GH_TOKEN")
SECRET_LIKE = re.compile(r"(sk-ant-[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")
ERROR_CMD = re.compile(r"::error[^:]*::(.*)")
EXC = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Interrupt|Exit|Timeout))(?::\s*(.*))?$")
CJK = re.compile(r"[぀-ヿ㐀-鿿가-힣]")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s+")   # Actions 로그 시각 머리
WIN = 10   # 기사 글 조각으로 보는 길이
URL = re.compile(r"https?://\S+")
SENTENCE = re.compile(r"(?:[^\W\d_]{2,}\W+){2,}[^\W\d_]{2,}")   # 낱말 3개 이상 이어진 문장꼴 (로마자 기사 제목일 수 있음, 구현 리뷰 M1)
NO_POST = {6, 7}   # 몇 분이면 끝나는 단계는 기록만 하고 올리지 않는다 — 상태 커밋·Pages 빌드 줄이기 (시간당 약 10회 권장, 계획 리뷰 2·3차)
LAST_HIDDEN = "로그 마지막 줄은 글이 들어 있어 생략 — Actions 로그 확인"
NO_LOG = "발행 준비(설치·캐시)에서 실패 — Actions 로그 확인"
RECENT = 7   # 최근 완료 기록 개수 (S61: 화면이 완료 예정 시각을 이 기록의 중앙값으로 낸다)
KST = timezone(timedelta(hours=9))


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- 오류 한 줄 ----------
def _clean(line: str) -> str:
    return STAMP.sub("", ANSI.sub("", line)).strip()


def extract_error(texts: list[str]) -> str:
    """앞 로그부터: `::error…::` 문장(마지막 것) → 파이썬 예외 줄(마지막 것) → 마지막 줄. 없으면 ""."""
    for text in texts:
        lines = [_clean(x) for x in text.splitlines()]
        lines = [x for x in lines if x]
        if not lines:
            continue
        errs = [m.group(1).strip() for x in lines if (m := ERROR_CMD.search(x))]
        if errs:
            return errs[-1]
        exc = [x for x in lines if EXC.match(x)]
        if exc:
            m = EXC.match(exc[-1])
            kind, msg = m.group(1), (m.group(2) or "").strip()
            bare = URL.sub(" ", msg)
            msg = URL.sub("<주소>", msg)
            if CJK.search(bare) or SENTENCE.search(bare):   # 한글·한자·가나나 문장꼴 = 기사·AI 글일 수 있음
                return kind
            return f"{kind}: {msg}" if msg else kind
        last = URL.sub("<주소>", lines[-1])
        bare = URL.sub(" ", lines[-1])
        # 마지막 줄은 아무 출력이나 될 수 있다(1면 제목 print, AI 출력) — 한글·문장꼴이면 싣지 않는다 (계획 리뷰 3차 M2)
        return LAST_HIDDEN if CJK.search(bare) or SENTENCE.search(bare) else last
    return ""


def secret_values(env=os.environ) -> list[str]:
    out = []
    for k in SECRET_ENV:
        v = (env.get(k) or "").strip()
        if len(v) >= 4:
            out.append(v)
            if k == "READER_URL":
                host = urlparse(v).hostname
                if host:
                    out.append(host)
    return sorted(set(out), key=len, reverse=True)


def article_samples(date: str) -> list[str]:
    """tools/verify_site.py 와 같은 표본: 기사 제목·리드 앞 30자·사설 제목 (8자 이상)."""
    p = ROOT / "data" / "raw" / f"{date}.edition.json"
    try:
        ed = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for ps in (ed.get("sections") or {}).values():
        for it in ps:
            out.append(it.get("title") or "")
            if len(it.get("lead") or "") >= 30:
                out.append(it["lead"][:30])
    for row in (ed.get("opinion") or {}).get("editorials", []):
        out.append(row.get("title") or "")
    return [s for s in out if len(s) >= 8]


def scrub(msg: str, secrets: list[str], samples: list[str]) -> str:
    for s in secrets:
        msg = msg.replace(s, "***")
    msg = SECRET_LIKE.sub("***", msg)
    msg = URL.sub("<주소>", msg)
    if samples:
        wins = {msg[i:i + WIN] for i in range(len(msg) - WIN + 1)}
        hit = any(s in msg if len(s) <= WIN else any(s[i:i + WIN] in wins for i in range(len(s) - WIN + 1)) for s in samples)   # 10자 이하 표본은 통째로
        if hit:
            kind = EXC.match(msg)
            msg = (kind.group(1) + " — " if kind else "") + "(기사 글이 들어 있어 생략)"
    msg = " ".join(msg.split())
    return msg if len(msg) <= MAX else msg[:MAX - 1] + "…"


# ---------- 단계 기록 ----------
def read_step() -> dict | None:
    try:
        return json.loads(STEP_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_step(d: dict) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    STEP_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def fallback_date(env=os.environ) -> str:
    if env.get("EDITION_DATE"):
        return env["EDITION_DATE"]
    try:
        sys.path.insert(0, str(ROOT))
        from pipeline.prepare import current_edition
        from pipeline.settings import load_config
        return current_edition(datetime.now(timezone.utc), load_config()).isoformat()
    except Exception:
        return (datetime.now(timezone(timedelta(hours=9))) - timedelta(minutes=330)).date().isoformat()


def payload(date: str, state: str, step: int, started: str, message: str = "", env=os.environ) -> dict:
    run = ""
    if env.get("GITHUB_RUN_ID"):
        run = f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/{env.get('GITHUB_REPOSITORY', '')}/actions/runs/{env['GITHUB_RUN_ID']}"
    step = max(1, min(len(STEPS), step))
    return {"date": date, "state": state, "step": step, "steps": len(STEPS), "label": STEPS[step - 1],
            "message": message, "started": started, "updated": now_iso(), "run": run}


# ---------- 올리기 ----------
def _decode(content) -> dict:
    try:
        return json.loads(base64.b64decode(content or "").decode("utf-8"))
    except Exception:
        return {}


def _parse(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return None


def regular_run(body: dict, env=os.environ) -> bool:
    """최근 기록에 넣을 실행 (S61 계획 리뷰 B2·M1): render_only 가 아니고, 그 호 날짜 KST 05:00~09:00 에 시작한 실행."""
    if env.get("RENDER_ONLY") == "1":
        return False
    st = _parse(body.get("started", ""))
    if not st or st.tzinfo is None:
        return False
    k = st.astimezone(KST)
    return k.date().isoformat() == body.get("date") and 5 <= k.hour < 9


def merge_recent(old, body: dict, add: bool) -> list:
    """옛 recent 를 이어받고(add 면 이 실행을 덧붙여) 날짜 순 최근 RECENT 개. 깨진 항목은 버린다."""
    rows = {}
    for r in old if isinstance(old, list) else []:
        if isinstance(r, dict) and isinstance(r.get("date"), str) and _parse(r.get("started", "")) and _parse(r.get("finished", "")):
            rows[r["date"]] = {"date": r["date"], "started": r["started"], "finished": r["finished"]}
    if add:
        rows[body["date"]] = {"date": body["date"], "started": body["started"], "finished": body["updated"]}
    return [rows[d] for d in sorted(rows)][-RECENT:]


def put(body: dict, env=os.environ, opener=urllib.request.urlopen, add_recent: bool = False) -> str:
    token, repo = env.get("STATUS_TOKEN"), env.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return "토큰 없음 — 올리지 않음"
    branch = env.get("STATUS_BRANCH", "main")
    url = f"https://api.github.com/repos/{repo}/contents/{PATH}"
    head = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "newspaper-status"}
    last = ""
    for _ in range(2):   # sha 가 바뀌어 409·422 면 한 번 더
        try:
            sha = None
            old = {}
            try:
                with opener(urllib.request.Request(f"{url}?ref={branch}", headers=head), timeout=15) as r:
                    cur = json.loads(r.read().decode("utf-8"))
                sha = cur.get("sha")
                old = _decode(cur.get("content"))
                if old.get("date", "") > body["date"] and old.get("state") in ("running", "error"):
                    return f"더 새 호({old['date']} {old['state']}) 상태가 있어 덮지 않음"   # 계획 리뷰 2차 M3
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
            # 원격을 읽었거나(키가 없거나 깨졌으면 빈 목록) 404 일 때만 여기 온다 — 옛 기록을 이어받는다 (S61 계획 리뷰 B1)
            body = {**body, "recent": merge_recent(old.get("recent") if isinstance(old, dict) else None, body, add_recent)}
            content = base64.b64encode((json.dumps(body, ensure_ascii=False, indent=1) + "\n").encode("utf-8")).decode()
            data = {"message": f"상태: {body['date']} {body['state']} {body['step']}/{body['steps']} {body['label']}",
                    "content": content, "branch": branch}
            if sha:
                data["sha"] = sha
            req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), method="PUT",
                                         headers={**head, "Content-Type": "application/json"})
            with opener(req, timeout=15) as r:
                return f"올림 ({r.status})"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code not in (409, 422):
                break
        except Exception as e:   # 네트워크 등
            last = type(e).__name__
            break
    return f"못 올림 ({last})"


def cmd_set(date: str, step: int, env=os.environ, opener=urllib.request.urlopen) -> str:
    if not date:
        return "날짜 없음 — 건너뜀"
    cur = read_step()
    if step == 1:
        cur = {"date": date, "step": 1, "started": now_iso()}
    elif not cur or cur.get("date") != date:
        return "이 실행에서 시작하지 않은 호 — 건너뜀"
    cur["step"] = step
    write_step(cur)   # 올리기 전에 기록 — 올리기가 실패해도 이 실행의 다음 단계·오류는 이 기록으로 간다
    if step in NO_POST:
        return "기록만 (짧은 단계)"
    return put(payload(date, "running", step, cur["started"], env=env), env, opener)


def cmd_done(date: str, env=os.environ, opener=urllib.request.urlopen) -> str:
    cur = read_step()
    if not date or not cur or cur.get("date") != date:
        return "이 실행에서 시작하지 않은 호 — 건너뜀"
    body = payload(date, "done", cur.get("step", 7), cur["started"], env=env)
    return put(body, env, opener, add_recent=regular_run(body, env))


def cmd_fail(cancelled: bool, env=os.environ, opener=urllib.request.urlopen) -> str:
    cur = read_step() or {}
    date = cur.get("date") or fallback_date(env)
    if not cur and (ROOT / "docs" / "archive" / date / "index.html").exists():
        return "이 실행이 시작하지 않았고 이미 발행된 호 — 건너뜀"   # 이미 발행돼 건너뛴 실행의 다른 실패 (계획 리뷰 3차 M3)
    step = cur.get("step", 1)
    started = cur.get("started") or now_iso()
    texts = []
    for p in LOGS:
        try:
            texts.append(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    msg = extract_error(texts) if texts else NO_LOG
    if cancelled:
        msg = "실행이 취소됐거나 시간이 초과됨" + (f" — {msg}" if msg else "")
    msg = scrub(msg or "오류 문장 없음 (Actions 로그 확인)", secret_values(env), article_samples(date))
    return put(payload(date, "error", step, started, msg, env), env, opener)


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        if argv[:1] == ["set"] and len(argv) >= 3:
            out = cmd_set(argv[1], int(argv[2]))
        elif argv[:1] == ["done"] and len(argv) >= 2:
            out = cmd_done(argv[1])
        elif argv[:1] == ["fail"]:
            out = cmd_fail("--cancelled" in argv)
        else:
            out = "사용법: set <날짜> <단계> | done <날짜> | fail [--cancelled]"
        print(f"발행 상태: {out}")
    except Exception as e:   # 상태 때문에 발행을 멈추지 않는다
        print(f"::warning::발행 상태를 올리지 못함 ({type(e).__name__})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
