"""관심 학습값 주간 반영 (S30b).

지면 설정 창의 슬라이더·키워드(기기 → Worker KV, S30a)를 발행이 주(ISO)마다 한 번 받아 data/interests-learned.json 에 쓰고(커밋),
설정을 읽을 때 interests.yaml 위에 덮는다. interests.yaml 원문(주석)은 손대지 않는다.
- 분야 가중치: 학습값이 있는 분야는 그 값, 없는 분야는 interests.yaml 대로
- 덜 보기(연속 보도 제외 등에 쓰임): 가중치가 default_weight 보다 낮은 분야
- 키워드: 학습 목록
받기 실패·키 없음·잘못된 값이면 아무것도 바꾸지 않는다 (발행은 계속).
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from .fsutil import read_json, write_atomic
from .settings import TOPICS, Interests

MAX_W, MAX_KW, MAX_KW_LEN, MAX_KNOWN, MAX_KNOWN_LEN = 3.0, 30, 30, 100, 40


def learned_path(root: Path) -> Path:
    return Path(root) / "data" / "interests-learned.json"


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def clean(prefs) -> dict | None:
    """Worker 가 돌려준 값을 확인해 쓸 모양으로 (worker/src/prefs.js 와 같은 규칙). 틀리면 None."""
    if not isinstance(prefs, dict) or prefs.get("v") != 1:
        return None
    w, kws = prefs.get("weights"), prefs.get("keywords")
    if not isinstance(w, dict) or not isinstance(kws, list) or len(kws) > MAX_KW or not isinstance(prefs.get("updated"), str):
        return None
    weights = {}
    for k, v in w.items():
        if k not in TOPICS or isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= MAX_W:
            return None
        weights[k] = round(float(v), 2)
    keywords: list[str] = []
    for k in kws:
        if not isinstance(k, str) or not k.strip() or len(k.strip()) > MAX_KW_LEN:
            return None
        if k.strip() not in keywords:
            keywords.append(k.strip())
    known = clean_known(prefs.get("known", []))
    if known is None:
        return None
    return {"weights": weights, "keywords": keywords, "known": known, "updated": prefs["updated"]}


def clean_known(v) -> list[str] | None:
    """아는 경제 개념 목록 (S31a). 틀리면 None."""
    if not isinstance(v, list) or len(v) > MAX_KNOWN:
        return None
    out: list[str] = []
    for k in v:
        if not isinstance(k, str) or not k.strip() or len(k.strip()) > MAX_KNOWN_LEN:
            return None
        if k.strip() not in out:
            out.append(k.strip())
    return out


def fetch_known(rc: dict | None, fetcher=fetch) -> list[str]:
    """발행마다 Worker 의 /prefs 에서 아는 경제 개념만 (S31a — 관심 가중치와 달리 주간이 아니라 바로 다음 호부터). 실패하면 []."""
    if not rc:
        return []
    try:
        got = fetcher(rc)
    except Exception:  # noqa: BLE001 — 못 받으면 아는 개념 없이 해설
        return []
    prefs = got.get("prefs") if isinstance(got, dict) and got.get("ok") else None
    return (clean_known(prefs.get("known", [])) or []) if isinstance(prefs, dict) else []


def fetch(rc: dict, timeout: float = 15.0):
    req = urllib.request.Request(rc["url"] + "/prefs", headers={"X-Reader-Key": rc["key"], "User-Agent": "newspaper-pipeline"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 — 주소는 발행 환경변수(READER_URL)에서만
        return json.loads(r.read().decode("utf-8"))


def learn(root: Path, d: date, rc: dict | None, fetcher=fetch) -> dict:
    """이번 주에 아직 안 합쳤으면 받아서 쓴다. 결과 요약을 돌려준다 (발행 로그용)."""
    path = learned_path(root)
    week = iso_week(d)
    old = read_json(path, {})
    if old.get("week") == week:
        return {"status": "이번 주 이미 반영", "week": week}
    if not rc:
        return {"status": "건너뜀: 중계 서버 주소·키 없음"}
    try:
        got = fetcher(rc)
    except Exception as e:  # noqa: BLE001 — 받기 실패는 발행을 멈추지 않는다
        return {"status": f"건너뜀: 받기 실패 ({type(e).__name__})"}
    prefs = clean(got.get("prefs") if isinstance(got, dict) and got.get("ok") else None)
    if prefs is None:
        return {"status": "건너뜀: 학습값 없음 또는 잘못됨"}
    out = {"week": week, "edition": d.isoformat(), "applied": datetime.now(timezone.utc).isoformat(timespec="seconds"), **prefs}
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    return {"status": "반영", "week": week, "topics": len(prefs["weights"]), "keywords": len(prefs["keywords"])}


def overlay(interests: Interests, learned: dict) -> Interests:
    """interests.yaml 값 위에 학습값을 덮은 설정. 원래 분야 가중치·키워드(base_*)와 반영 주(learned_week)를 함께 둔다."""
    from .interest import build_interest_table

    prefs = clean({"v": 1, **{k: learned.get(k) for k in ("weights", "keywords", "updated")}})
    base = build_interest_table(interests).topic_weights
    if prefs is None:
        return interests.model_copy(update={"base_weights": base, "base_keywords": list(interests.keywords)})
    weights = {**base, **prefs["weights"]}
    return interests.model_copy(update={
        "topics": weights,
        "less": [t for t in TOPICS if weights[t] < interests.default_weight],
        "keywords": prefs["keywords"],
        "base_weights": base,
        "base_keywords": list(interests.keywords),
        "learned_week": learned.get("week"),
    })


def apply(interests: Interests, root: Path) -> Interests:
    learned = read_json(learned_path(root), None)
    return overlay(interests, learned if isinstance(learned, dict) else {})
