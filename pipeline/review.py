"""편집 리뷰 받기와 주간 자동 조정 (S38c, 20차 요청).

설정 창 "편집 리뷰" 탭에서 기사마다 고른 평가(기기 → Worker KV, worker/src/reviews.js)를 발행(learn 단계)이 매일 받아
data/reviews/<호>.json 에 쓴다(커밋) — **메모는 빼고** (공개 저장소, 메모는 KV 에만 60일).
주(ISO)마다 한 번, 최근 28일 리뷰로 편집 가중치를 조금씩 바꿔 data/editing-learned.json 에 쓰고, load_config 가 config.yaml 위에 덮는다.
- 방향: up +1, down −1, drop −1.5, ok 0. 방향 있는 리뷰가 10건 이상일 때만 바꾼다 (모자라면 그 주 다음 발행에서 다시 본다)
- 가중치(주목·중요·머리기사·연속성): 지표마다 g = 평균(방향 × (그 기사 지표 − 리뷰한 기사들의 평균)), 새 값 = 지금 × (1 + 0.5·g),
  config.yaml 값의 0.7~1.3배 안. 관심도 가중치는 손대지 않는다 (관심도 탭이 따로)
- 분야 중요도: 분야별 리뷰 3건 이상(방향 있는 것 1건 이상)이면 방향 평균 × 0.1 만큼(주당 ±0.1), config.yaml 값의 0.6~1.4배 안
- 되돌리기: 설정 창 → Worker KV editing-reset 시각. 그 시각이 지난번에 본 것보다 새것이면 학습값을 지우고, 그날 이전 호의 리뷰는 더 쓰지 않는다
받기 실패·키 없음·잘못된 값이면 아무것도 바꾸지 않는다 (발행은 계속).
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .fsutil import read_json, write_atomic
from .learned import iso_week
from .settings import TOPICS, Config

VERDICT_DIR = {"ok": 0.0, "up": 1.0, "down": -1.0, "drop": -1.5}
SCORE_KEYS = ("attention", "importance", "headline", "continuity", "interest", "final")
TUNED = ("attention", "importance", "headline", "continuity")
LABEL = {"attention": "주목도", "importance": "중요도", "headline": "머리기사", "continuity": "연속성"}
WINDOW_DAYS, MIN_DIRECTED, MIN_TOPIC, RATE = 28, 10, 3, 0.5
W_BOUNDS, T_BOUNDS, T_STEP = (0.7, 1.3), (0.6, 1.4), 0.1
HISTORY_KEEP = 12
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def learned_path(root: Path) -> Path:
    return Path(root) / "data" / "editing-learned.json"


def reviews_dir(root: Path) -> Path:
    return Path(root) / "data" / "reviews"


def clean_record(rec) -> dict | None:
    """Worker 가 돌려준 호 기록 하나를 메모 없이 저장할 모양으로. 틀리면 None (worker/src/reviews.js 와 같은 규칙)."""
    if not isinstance(rec, dict) or rec.get("v") != 1 or not isinstance(rec.get("edition"), str) or not DAY.match(rec["edition"]):
        return None
    items = rec.get("items")
    if not isinstance(items, dict):
        return None
    out = {}
    for iid, r in items.items():
        if not isinstance(iid, str) or not ID.match(iid) or not isinstance(r, dict) or r.get("verdict") not in VERDICT_DIR:
            return None
        sc = r.get("scores")
        if not isinstance(sc, dict):
            return None
        scores = {}
        for k in SCORE_KEYS:
            v = sc.get(k)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
                return None
            scores[k] = round(float(v), 4)
        topic = r.get("topic") if r.get("topic") in TOPICS else ""
        rank = r.get("rank") if isinstance(r.get("rank"), int) and not isinstance(r.get("rank"), bool) else 0
        out[iid] = {"verdict": r["verdict"], "topic": topic, "section": str(r.get("section", ""))[:20], "rank": rank, "scores": scores}
    return {"v": 1, "edition": rec["edition"], "items": out, "updated": str(rec.get("updated", ""))[:40]}


def fetch(rc: dict, since: str, timeout: float = 15.0):
    url = rc["url"] + "/reviews?" + urllib.parse.urlencode({"from": since})
    req = urllib.request.Request(url, headers={"X-Reader-Key": rc["key"], "User-Agent": "newspaper-pipeline"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 — 주소는 발행 환경변수(READER_URL)에서만
        return json.loads(r.read().decode("utf-8"))


def load_reviews(root: Path, since: str, until: str) -> list[dict]:
    """data/reviews 의 since ≤ 호 ≤ until 기록에서 리뷰 한 건씩 (호·id 포함)."""
    out = []
    d = reviews_dir(root)
    if not d.exists():
        return out
    for f in sorted(d.glob("*.json")):
        if not since <= f.stem <= until:
            continue
        rec = clean_record(read_json(f, None))
        if not rec:
            continue
        out += [{"edition": rec["edition"], "id": iid, **r} for iid, r in rec["items"].items()]
    return out


def _clamp(v: float, base: float, bounds: tuple[float, float]) -> float:
    return min(base * bounds[1], max(base * bounds[0], v))


def adjust(reviews: list[dict], base_w: dict[str, float], cur_w: dict[str, float],
           base_t: dict[str, float], cur_t: dict[str, float]) -> tuple[dict, dict, list[dict]] | None:
    """리뷰로 가중치·분야 중요도 새 값. 방향 있는 리뷰가 MIN_DIRECTED 건 미만이면 None."""
    directed = [r for r in reviews if VERDICT_DIR[r["verdict"]]]
    if len(directed) < MIN_DIRECTED:
        return None
    mean = {k: sum(r["scores"][k] for r in reviews) / len(reviews) for k in TUNED}
    weights, changes = dict(cur_w), []
    for k in TUNED:
        g = sum(VERDICT_DIR[r["verdict"]] * (r["scores"][k] - mean[k]) for r in directed) / len(directed)
        new = round(_clamp(cur_w[k] * (1 + RATE * g), base_w[k], W_BOUNDS), 3)
        if abs(new - cur_w[k]) >= 0.001:
            changes.append({"kind": "weight", "key": k, "label": LABEL[k], "from": round(cur_w[k], 3), "to": new})
        weights[k] = new
    topics = dict(cur_t)
    for t in TOPICS:
        rs = [r for r in reviews if r["topic"] == t]
        if len(rs) < MIN_TOPIC or not any(VERDICT_DIR[r["verdict"]] for r in rs):
            continue
        step = max(-T_STEP, min(T_STEP, sum(VERDICT_DIR[r["verdict"]] for r in rs) / len(rs) * T_STEP))
        new = round(_clamp(cur_t[t] + step, base_t[t], T_BOUNDS), 3)
        if abs(new - cur_t[t]) >= 0.001:
            changes.append({"kind": "topic", "key": t, "label": TOPICS[t], "from": round(cur_t[t], 3), "to": new, "reviews": len(rs)})
        topics[t] = new
    return weights, topics, changes


def learn(root: Path, d: date, rc: dict | None, base: Config, fetcher=fetch) -> dict:
    """리뷰를 받아 쓰고, 이번 주에 아직 안 했으면 자동 조정. base 는 학습값을 덮지 않은 config.yaml. 요약을 돌려준다 (발행 로그용)."""
    if not rc:
        return {"status": "건너뜀: 중계 서버 주소·키 없음"}
    path = learned_path(root)
    old = read_json(path, {})
    old = old if isinstance(old, dict) else {}
    since = (d - timedelta(days=WINDOW_DAYS)).isoformat()
    try:
        got = fetcher(rc, since)
    except Exception as e:  # noqa: BLE001 — 받기 실패는 발행을 멈추지 않는다
        return {"status": f"건너뜀: 받기 실패 ({type(e).__name__})"}
    if not isinstance(got, dict) or not got.get("ok") or not isinstance(got.get("reviews"), list):
        return {"status": "건너뜀: 응답이 잘못됨"}
    saved = 0
    for rec in got["reviews"]:
        rec = clean_record(rec)   # 메모는 여기서 빠진다
        if not rec or rec["edition"] > d.isoformat():
            continue
        f = reviews_dir(root) / f"{rec['edition']}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(rec, ensure_ascii=False, indent=1) + "\n"
        if not f.exists() or f.read_text(encoding="utf-8") != text:
            write_atomic(f, text)
            saved += 1
    out = {"saved": saved}
    reset = got.get("reset")
    if isinstance(reset, str) and reset > old.get("reset_seen", ""):
        # 되돌리기: 학습값을 지우고, 되돌린 날까지의 호 리뷰는 더 쓰지 않는다
        old = {"v": 1, "reset_seen": reset, "since": reset[:10], "history": old.get("history", []),
               "reset_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        write_atomic(path, json.dumps(old, ensure_ascii=False, indent=2) + "\n")
        return {"status": "되돌림 — 자동 조정값을 지움", **out}
    week = iso_week(d)
    if old.get("week") == week:
        return {"status": "이번 주 이미 조정", "week": week, **out}
    lo = max(since, old.get("since", ""))
    reviews = [r for r in load_reviews(root, lo, d.isoformat()) if r["edition"] >= lo]
    base_w = {k: getattr(base.weights, k) for k in TUNED}
    base_t = dict(base.importance.topic_weights)
    cur_w = {k: float(old.get("weights", {}).get(k, base_w[k])) for k in TUNED}
    cur_t = {t: float(old.get("topic_importance", {}).get(t, base_t[t])) for t in TOPICS}
    res = adjust(reviews, base_w, cur_w, base_t, cur_t)
    if res is None:
        n = sum(1 for r in reviews if VERDICT_DIR[r["verdict"]])
        return {"status": f"리뷰 부족 (방향 있는 것 {n}/{MIN_DIRECTED}건)", **out}
    weights, topics, changes = res
    applied = datetime.now(timezone.utc).isoformat(timespec="seconds")
    hist = (old.get("history", []) + [{"week": week, "edition": d.isoformat(), "reviews": len(reviews), "changes": changes}])[-HISTORY_KEEP:]
    new = {"v": 1, "week": week, "edition": d.isoformat(), "applied": applied, "reviews": len(reviews),
           "weights": weights, "topic_importance": topics, "changes": changes, "history": hist,
           **{k: old[k] for k in ("reset_seen", "since", "reset_at") if k in old}}
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps(new, ensure_ascii=False, indent=2) + "\n")
    return {"status": "조정", "week": week, "reviews": len(reviews), "changes": len(changes), **out}


def overlay(cfg: Config, learned: dict) -> Config:
    """config.yaml 위에 자동 조정값을 덮은 설정. 잘못된 값은 그 칸만 건너뛴다."""
    if not isinstance(learned, dict):
        return cfg
    lw, lt = learned.get("weights"), learned.get("topic_importance")
    upd = {}
    if isinstance(lw, dict):
        w = {k: float(v) for k, v in lw.items() if k in TUNED and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v <= 5}
        if w:
            upd["weights"] = cfg.weights.model_copy(update=w)
    if isinstance(lt, dict):
        t = {k: float(v) for k, v in lt.items() if k in TOPICS and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 5}
        if t:
            upd["importance"] = cfg.importance.model_copy(update={"topic_weights": {**cfg.importance.topic_weights, **t}})
    return cfg.model_copy(update=upd) if upd else cfg


def apply(cfg: Config, root: Path) -> Config:
    return overlay(cfg, read_json(learned_path(root), None))
