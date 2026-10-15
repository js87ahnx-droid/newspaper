"""후보 피드 URL 실측: 응답 코드, 항목 수, 최신 기사 시각, 요약 포함 여부.

사용: python tools/probe_feeds.py candidates.yaml > result.json
candidates.yaml 형식: {매체명: [url, ...]}
"""
from __future__ import annotations

import asyncio
import calendar
import json
import sys
from datetime import datetime, timezone

import feedparser
import httpx
import yaml

UA = "Mozilla/5.0 (personal news digest; RSS reader)"


def _ts(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return None


async def probe(client: httpx.AsyncClient, url: str) -> dict:
    out: dict = {"url": url}
    try:
        r = await client.get(url)
        out["status"] = r.status_code
        out["final_url"] = str(r.url)
        if r.status_code != 200:
            return out
        feed = feedparser.parse(r.content)
        entries = feed.entries
        out["items"] = len(entries)
        out["bozo"] = bool(feed.bozo) and not entries
        stamps = [t for t in (_ts(e) for e in entries) if t]
        out["dated"] = len(stamps)
        if stamps:
            newest = max(stamps)
            out["newest_utc"] = newest.isoformat()
            out["age_hours"] = round((datetime.now(timezone.utc) - newest).total_seconds() / 3600, 1)
            # 피드가 담고 있는 시간 폭 — 수집 시간창(11시간)을 다 덮는지 판단용
            out["span_hours"] = round((newest - min(stamps)).total_seconds() / 3600, 1)
        summaries = [e.get("summary", "") for e in entries]
        out["with_summary"] = sum(1 for s in summaries if len(s.strip()) >= 30)
        if entries:
            out["sample_title"] = entries[0].get("title", "")[:80]
    except Exception as e:  # 실측 도구라 모든 실패를 기록하고 넘어간다
        out["error"] = f"{type(e).__name__}: {e}"[:200]
    return out


async def main(path: str) -> None:
    cands = yaml.safe_load(open(path, encoding="utf-8"))
    async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=20, follow_redirects=True) as client:
        tasks = {(name, url): probe(client, url) for name, urls in cands.items() for url in urls}
        results = await asyncio.gather(*tasks.values())
    report: dict[str, list] = {}
    for (name, _), res in zip(tasks, results):
        report.setdefault(name, []).append(res)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
