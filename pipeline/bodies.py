"""본문 읽기 (S14, D13·D16): 발행 때 러너에서 기사 페이지를 받아 본문만 뽑는다.

원칙
- 본문은 **메모리에서만** 쓴다. 파일·캐시·지면 어디에도 쓰지 않는다 (공개 저장소). 이 모듈의 함수는 dict 를 돌려줄 뿐
  저장하지 않으며, 부르는 쪽(llm.analyze)도 LLM 프롬프트에만 넣는다.
- 받기·추출 실패는 흔하다 (유료 벽, 봇 차단, 자바스크립트 페이지). 실패하면 그 기사는 RSS 리드로 대신한다.
- Google 뉴스 경유 주소(news.google.com/rss/articles/…)는 원래 기사 주소로 풀어서 받는다.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlsplit

import httpx

# 실제 브라우저처럼 보이지 않으면 막는 매체가 많다 (본문 추출은 사람이 열어 보는 것과 같은 한 번의 요청)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
PER_HOST = 2        # 한 매체에 동시에 여는 요청 수 (몰아서 받으면 막는 곳이 있다 — 경향신문 실측)
MIN_CHARS = 200     # 이보다 짧으면 본문이 아니라 안내문·요약으로 본다
MAX_CHARS = 4000    # LLM 에 넣는 본문 상한 (앞부분이 핵심)


@dataclass
class Body:
    url: str            # 실제로 받은 주소 (Google 뉴스면 풀린 주소)
    text: str | None    # 본문 (실패하면 None)
    status: str         # ok / http 403 / 짧음 / 추출 실패 / google 풀기 실패 …


def is_google(url: str) -> bool:
    return url.startswith("https://news.google.com/") and "/articles/" in url


async def _decode_google(urls: list[str], timeout: float) -> dict[str, str | None]:
    if not urls:
        return {}
    try:
        from googlenewsdecoder import gnews_decoder_async

        res = await gnews_decoder_async(urls, timeout=timeout, concurrency=4)
    except Exception:  # 라이브러리·구글 쪽 변경 — 그 기사들만 리드로
        return {u: None for u in urls}
    return {u: (r.get("decoded_url") if r.get("success") else None) for u, r in zip(urls, res)}


_TAG = re.compile(r"<[^>]+>")
_FUSION = re.compile(r"Fusion\.globalContent\s*=\s*(\{.*?\});\s*Fusion\.", re.S)
_LDJSON = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)


def _strip(html: str) -> str:
    return unescape(_TAG.sub("", html)).strip()


def _from_fusion(html: str) -> str | None:
    """Arc 출판 시스템(조선일보 등): 본문이 자바스크립트 데이터로만 들어 있다."""
    m = _FUSION.search(html)
    if not m:
        return None
    try:
        els = json.loads(m.group(1)).get("content_elements") or []
    except ValueError:
        return None
    paras = [_strip(e.get("content", "")) for e in els if e.get("type") == "text"]
    return "\n".join(p for p in paras if p) or None


def _from_ldjson(html: str) -> str | None:
    for block in _LDJSON.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for d in data if isinstance(data, list) else [data, *(data.get("@graph") or [])]:
            if isinstance(d, dict) and isinstance(d.get("articleBody"), str):
                return _strip(d["articleBody"])
    return None


def extract(html: str, url: str) -> str | None:
    """trafilatura 가 먼저, 그다음 페이지에 실린 구조화 데이터. 가장 긴 것을 쓴다."""
    import trafilatura

    cands = [
        trafilatura.extract(html, url=url, include_comments=False, include_tables=False, include_images=False,
                            favor_precision=True, deduplicate=True),
        _from_fusion(html),
        _from_ldjson(html),
    ]
    cands = [c.strip() for c in cands if c and c.strip()]
    return max(cands, key=len) if cands else None


async def fetch_bodies(urls: list[str], timeout: float = 15.0, concurrency: int = 8, client=None) -> dict[str, Body]:
    """원래 주소(urls) → Body. 같은 주소는 한 번만 받는다."""
    urls = list(dict.fromkeys(urls))
    decoded = await _decode_google([u for u in urls if is_google(u)], timeout)
    own = client is None
    client = client or httpx.AsyncClient(
        headers={"User-Agent": UA, "Accept-Language": "ko,en;q=0.8,ja;q=0.6"}, timeout=timeout, follow_redirects=True
    )
    sem = asyncio.Semaphore(concurrency)
    hosts: dict[str, asyncio.Semaphore] = {}

    async def one(u: str) -> tuple[str, Body]:
        real = decoded.get(u, u) if is_google(u) else u
        if real is None:
            return u, Body(u, None, "google 풀기 실패")
        host = hosts.setdefault(urlsplit(real).netloc, asyncio.Semaphore(PER_HOST))
        async with sem, host:
            try:
                r = await client.get(real)
            except httpx.HTTPError as e:
                return u, Body(real, None, f"받기 실패 {type(e).__name__}")
        if r.status_code != 200:
            return u, Body(real, None, f"http {r.status_code}")
        try:
            text = await asyncio.to_thread(extract, r.text, real)
        except Exception as e:
            return u, Body(real, None, f"추출 실패 {type(e).__name__}")
        if not text:
            return u, Body(real, None, "추출 실패")
        if len(text) < MIN_CHARS:
            return u, Body(real, None, "짧음")
        return u, Body(real, text[:MAX_CHARS], "ok")

    try:
        pairs = await asyncio.gather(*(one(u) for u in urls))
    finally:
        if own:
            await client.aclose()
    return dict(pairs)


def copied_span(output: str, bodies: list[str], n: int = 40) -> str | None:
    """LLM 출력이 본문을 그대로 옮겼는지: 공백을 뺀 n 글자 이상이 본문과 똑같이 겹치면 그 조각을 돌려준다.
    (지면에는 LLM 이 쓴 글만 나가야 한다 — D16)"""
    def squash(s: str) -> str:
        return "".join(s.split())

    out = squash(output)
    if len(out) < n:
        return None
    grams = {out[i : i + n] for i in range(0, len(out) - n + 1)}
    for b in bodies:
        sb = squash(b)
        for i in range(0, len(sb) - n + 1):
            if sb[i : i + n] in grams:
                return sb[i : i + n]
    return None
