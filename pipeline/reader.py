"""원문 재배열 보기 연결 (S17, D14): 지면의 기사 제목을 누르면 중계 서버(worker/)가 원문을 재배열해 보여 준다.

- 중계 서버 주소·접근 키는 발행 환경변수(READER_URL·READER_KEY, GitHub Secrets)에서만 온다. 키는 암호화된 지면 안에만 들어간다.
  둘 중 하나라도 없으면 지금처럼 원문 링크만 쓴다.
- Google 뉴스 경유 주소(news.google.com/rss/articles/…)는 중계 서버가 받을 수 없으므로(허용목록 밖) 발행 때 원래 주소로 풀어 둔다.
  주소만 저장한다 (본문 아님).
- sources.yaml 에서 reader: false 인 매체(봇 차단·유료 벽·자바스크립트 페이지 — 실측)는 누르면 바로 원문으로 간다.
"""
from __future__ import annotations

import asyncio
import os

from .bodies import _decode_google, is_google
from .settings import Sources


def config() -> dict | None:
    url, key = os.environ.get("READER_URL", "").strip().rstrip("/"), os.environ.get("READER_KEY", "").strip()
    local = url.startswith(("http://127.0.0.1", "http://localhost"))   # 로컬 시험 (wrangler dev)
    if not url or not key or not (url.startswith("https://") or local):
        return None
    return {"url": url, "key": key}


def page_urls(edition: dict) -> list[str]:
    """지면에 링크로 나가는 기사 주소: 각 이슈 대표 기사 + 입장 차이에 보이는 기사(그룹당 2건)."""
    items = [it for ps in edition["sections"].values() for it in ps] + edition.get("compare", [])
    urls = [it["url"] for it in items]
    urls += [a["url"] for it in items for g in it.get("stance", {}).get("lean", []) for a in g["articles"][:2]]
    op = edition.get("opinion") or {}
    urls += [e["url"] for c in op.get("compare", []) for g in c["groups"] for e in g["editorials"]]
    urls += [e["url"] for e in op.get("editorials", []) + op.get("columns", [])]
    # 분석·해설 면(S22c)·지정 칼럼(S22d)도 — 빠져 있어 Google 뉴스로 받는 조선비즈 지정 칼럼이 원문 창에서 못 열렸다 (S18)
    urls += [a["url"] for a in (edition.get("analysis") or []) + (edition.get("picks") or [])]
    return list(dict.fromkeys(urls))


def resolve_google(edition: dict, timeout: float = 20.0) -> dict:
    """지면의 Google 뉴스 주소를 원래 주소로 풀어 edition["read_urls"] 에 둔다. 실패한 주소는 원문 링크로만 남는다."""
    g = [u for u in page_urls(edition) if is_google(u)]
    dec = asyncio.run(_decode_google(g, timeout)) if g else {}
    edition["read_urls"] = {u: r for u, r in dec.items() if r}
    return {"google": len(g), "resolved": len(edition["read_urls"])}


def read_url_fn(edition: dict, sources: Sources):
    """템플릿용: (주소, 매체) → 읽기 화면으로 열 주소. 열 수 없으면 빈 문자열 (그러면 그냥 원문 링크)."""
    skip = {s.name for s in sources.sources if not s.reader}
    mapped = edition.get("read_urls", {})

    def read_url(url: str, source: str | None = None) -> str:
        if not url or source in skip:
            return ""
        if is_google(url):
            return mapped.get(url, "")
        return url

    return read_url
