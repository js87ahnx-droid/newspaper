"""sources.yaml 의 켜진 피드가 지금 실제로 동작하는지 점검한다.

판정 기준 (피드 하나당):
  - HTTP 200, 항목 1개 이상
  - date_source=feed 이면 항목 절반 이상에 발행 시각이 있고, 최신 기사가 48시간 이내
사용: python tools/check_sources.py  (실패가 있으면 종료 코드 1)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.settings import load_sources  # noqa: E402
from probe_feeds import UA, probe  # noqa: E402

MAX_AGE_H = 48


def judge(feed, r: dict) -> str | None:
    if "error" in r:
        return r["error"]
    if r.get("status") != 200:
        return f"HTTP {r.get('status')}"
    if not r.get("items"):
        return "항목 0개"
    if feed.date_source == "feed":
        if r.get("dated", 0) < r["items"] / 2:
            return f"발행 시각 있는 항목 {r.get('dated')}/{r['items']}"
        if r.get("age_hours", 1e9) > MAX_AGE_H:
            return f"최신 기사가 {r['age_hours']}시간 전 (갱신 중단 의심)"
    return None


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    feeds = [(s.name, f) for s in load_sources().sources if s.enabled for f in s.feeds]
    async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=20, follow_redirects=True) as client:
        results = await asyncio.gather(*(probe(client, f.url) for _, f in feeds))
    bad = 0
    for (name, f), r in zip(feeds, results):
        why = judge(f, r)
        mark = "OK " if why is None else "FAIL"
        bad += why is not None
        detail = why or (
            f"{r['items']}건, 요약 {r.get('with_summary')}건, 최신 {r.get('age_hours', '-')}h, "
            f"폭 {r.get('span_hours', '-')}h"
        )
        print(f"{mark} {name:20} {f.section:14} {detail}")
    print(f"\n켜진 피드 {len(feeds)}개 중 실패 {bad}개")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
