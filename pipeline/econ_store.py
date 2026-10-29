"""경제 해설 보관·재사용 (S33, 16차 요청 "지면과 함께 지워지면 비슷한 분석을 다시 돌리기 아깝다").

data/econ/<호>.json   그 호의 경제 해설(AI 가 쓴 글)·이슈 제목·특징 낱말·대표 기사 링크 — 기사 본문·리드 없음 (공개 저장소).
                      지난 호 지면(docs/archive)은 14일 뒤 지우지만 이 파일은 지우지 않는다.

원천은 enrich 가 끝난 data/raw/<호>.edition.json 의 it.llm.econ, 특징 낱말은 같은 호 data/history/<호>.json (edit 가 enrich 전에 씀).
해설을 새로 쓸 때 연속성과 같은 기준으로 가장 가까운 지난 해설을 찾아 프롬프트에 참고로 붙인다 (llm.econ_dive).
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from .fsutil import read_json, write_atomic

STORE_V = 1
ARTICLES = 3        # 해설당 기사 링크 상한 (data/history 와 같게)
PAST_DAYS = 180     # 지난 해설을 찾아보는 기간
PAST_MATCHES = 2    # 기사 하나에 붙이는 지난 해설 수


def _articles(item: dict) -> list[dict]:
    """대표 기사 링크 — 매체·제목·주소·발행 시각·언어만. 한국어·영어 먼저, 매체당 1건 (score.history_articles 와 같은 규칙)."""
    from .score import _plain_url

    arts = sorted(item.get("articles") or [], key=lambda a: (a.get("lang") != "ko", a.get("lang") != "en", a.get("published") or ""))
    out, seen = [], set()
    for a in arts:
        if a.get("source") in seen or not a.get("url"):
            continue
        seen.add(a.get("source"))
        out.append({"source": a.get("source"), "title": a.get("title"), "url": _plain_url(a["url"]),
                    "published": a.get("published"), "lang": a.get("lang")})
        if len(out) >= ARTICLES:
            break
    return out


def record(edition: dict, history: dict | None) -> dict:
    """한 호의 보관 기록. 해설이 붙은 지면 기사만 (skip·해설 없음은 빠진다)."""
    sigs = {x["id"]: x.get("signature") or [] for x in (history or {}).get("issues", [])}
    items = []
    for ps in edition.get("sections", {}).values():
        for it in ps:
            dive = (it.get("llm") or {}).get("econ")
            if not dive:
                continue
            items.append({"issue_id": it["issue_id"], "title": it.get("title", ""), "topic": it.get("topic"),
                          "signature": sigs.get(it["issue_id"], []),
                          **{k: dive.get(k) for k in ("concepts", "theory", "practice", "analysis", "watch")},
                          "articles": _articles(it)})
    return {"v": STORE_V, "edition": edition.get("edition"), "items": items}


def write(data: Path, day: str, edition: dict) -> Path | None:
    """data/econ/<호>.json 을 (다시) 쓴다. 해설이 하나도 없으면 쓰지 않는다."""
    rec = record(edition, read_json(data / "history" / f"{day}.json", None))
    rec["edition"] = day
    if not rec["items"]:
        return None
    path = data / "econ" / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def backfill(raw: Path, data: Path) -> list[str]:
    """data/raw 에 지면(edition)은 있는데 보관본이 없는 호를 채운다 (data/raw 는 14일만 남는다). 있는 보관본은 그대로. 쓴 호 날짜."""
    done = []
    for p in sorted(raw.glob("20??-??-??.edition.json")):
        day = p.name[:10]
        if (data / "econ" / f"{day}.json").exists():
            continue
        try:
            edition = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if write(data, day, edition):
            done.append(day)
    return done


def load_past(data: Path, today: date, days: int = PAST_DAYS) -> list[dict]:
    """오늘 호를 뺀 지난 days 일의 해설 (항목마다 date). 새 것부터."""
    out = []
    lo = (today - timedelta(days=days)).isoformat()
    for p in sorted((data / "econ").glob("20??-??-??.json"), reverse=True):
        day = p.stem
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or day >= today.isoformat() or day < lo:
            continue
        rec = read_json(p, None)
        for it in (rec or {}).get("items", []):
            out.append({**it, "date": day})
    return out


def match(signature: list[str], past: list[dict], n: int = PAST_MATCHES) -> list[dict]:
    """연속성과 같은 기준(score._match_key)으로 가까운 지난 해설 n건. 점수 높은 것부터, 같으면 최근 것. 같은 제목은 한 번."""
    from .score import _match_key

    if not signature:
        return []
    cands = []
    for i, it in enumerate(past):
        k = _match_key(signature, {"signature": it.get("signature") or []})
        if k:
            cands.append((k, it.get("date", ""), -i, it))
    cands.sort(key=lambda c: (c[0], c[1], c[2]), reverse=True)
    out, titles = [], set()
    for _, _, _, it in cands:
        if it.get("title") in titles:
            continue
        titles.add(it.get("title"))
        out.append(it)
        if len(out) >= n:
            break
    return out


def past_for(targets: list[dict], data: Path, today: date) -> dict[str, list[dict]]:
    """해설 대상 기사별 지난 해설 짝 {issue_id: [지난 해설]} — 특징 낱말은 오늘 호 data/history."""
    past = load_past(data, today)
    if not past:
        return {}
    hist = read_json(data / "history" / f"{today.isoformat()}.json", None) or {}
    sigs = {x["id"]: x.get("signature") or [] for x in hist.get("issues", [])}
    out = {}
    for it in targets:
        m = match(sigs.get(it["issue_id"], []), past)
        if m:
            out[it["issue_id"]] = m
    return out
