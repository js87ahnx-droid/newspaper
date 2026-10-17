"""매체 머리기사 (S14b, 2026-10-17 사용자 요청: "매일 신문사의 헤드라인이나 메인 뉴스 파악해서 가중치, 1면은 특히").

매체마다 sources.yaml 의 `headline` 목록을 앞에서부터 시도해 그날 머리기사 위 3건(순위·제목)을 얻는다.
- naver_a1: 네이버 '신문 보기'의 A1면(종이신문 1면) 기사 — 국내 일간지. 실린 순서가 곧 1면 배치 순서
- feed: 편집 순서로 정렬된 머리 피드 (BBC Top Stories, NYT HomePage — 실측 2026-10-17, 시간순 피드는 쓰지 않는다)
- homepage: 홈페이지 링크 순서. 메뉴·광고 링크는 그 매체의 그날 기사와 맞는 링크만 남겨 걸러 낸다

얻은 제목은 같은 매체의 그날 기사와 맞춘다 (`match`). 종이신문 제목은 온라인 제목과 다를 수 있어 어휘 겹침이나
임베딩 유사도로 맞추고, 애매하면 버린다. 저장하는 것은 제목·순위·주소뿐 (본문 없음).
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass
from datetime import date
from html import unescape
from urllib.parse import urljoin, urlsplit

import httpx
import numpy as np

from .bodies import UA
from .collect import Article
from .textutil import title_key

TOP_N = 3
RANK_WEIGHT = {1: 1.0, 2: 0.5, 3: 0.35}   # 1면 머리(1위)가 가장 크다

_A1 = re.compile(r'<em>(A?1)</em>면</span></h3>\s*<ul class="newspaper_article_lst">(.*?)</ul>', re.S)
_STRONG = re.compile(r"<strong>(.*?)</strong>", re.S)
_ANCHOR = re.compile(r'<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


@dataclass
class Headline:
    source: str
    rank: int
    title: str
    via: str                  # naver_a1 / feed / homepage
    url: str | None = None
    article_id: str | None = None
    how: str | None = None    # 맞춘 방법: url / title / embed (못 맞추면 None)
    group: int | None = None  # 같은 기사거리(여러 매체가 각자 다른 기사로 1면에 올린 같은 주제) 번호


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG.sub("", html))).strip()


def norm_url(u: str) -> str:
    s = urlsplit(u)
    host = s.netloc.lower().removeprefix("www.").removeprefix("m.")
    return (host + s.path).rstrip("/").lower()


def parse_naver_a1(html: str) -> list[str]:
    m = _A1.search(html)
    return [_text(t) for t in _STRONG.findall(m.group(2))][:TOP_N] if m else []


def parse_feed(xml: bytes) -> list[tuple[str, str]]:
    import feedparser

    return [(e.get("title", "").strip(), e.get("link", "")) for e in feedparser.parse(xml).entries[:TOP_N]]


def parse_homepage(html: str, base: str, arts: list[Article]) -> list[tuple[str, str]]:
    """홈페이지 링크를 순서대로 보며 그 매체의 그날 기사와 맞는 첫 TOP_N 건 (주소가 같거나 링크 글이 제목과 같음)."""
    urls = {norm_url(a.url): a for a in arts}
    titles = {title_key(a.title)[:24]: a for a in arts if len(title_key(a.title)) >= 8}
    out, seen = [], set()
    for href, inner in _ANCHOR.findall(html):
        text = _text(inner)
        key = title_key(text)[:24]
        a = urls.get(norm_url(urljoin(base, href))) or (titles.get(key) if len(key) >= 8 else None)
        if a and a.id not in seen:
            seen.add(a.id)
            out.append((a.title, a.url))
            if len(out) >= TOP_N:
                break
    return out


async def fetch(sources, edition: date, day_articles: list[Article], client=None) -> tuple[list[Headline], dict[str, str]]:
    """매체별 머리기사. 돌려주는 값: (머리기사 목록, 매체 → 상태)."""
    by_src: dict[str, list[Article]] = {}
    for a in day_articles:
        by_src.setdefault(a.source, []).append(a)
    own = client is None
    client = client or httpx.AsyncClient(headers={"User-Agent": UA, "Accept-Language": "ko,en;q=0.8,ja;q=0.6"},
                                         timeout=20, follow_redirects=True)

    async def one(src) -> tuple[str, list[Headline], str]:
        tried = []
        for h in src.headline:
            try:
                if h.kind == "naver_a1":
                    r = await client.get(f"https://media.naver.com/press/{h.press}/newspaper", params={"date": edition.strftime("%Y%m%d")})
                    rows = [(t, None) for t in parse_naver_a1(r.text)] if r.status_code == 200 else []
                elif h.kind == "feed":
                    r = await client.get(h.url)
                    rows = parse_feed(r.content) if r.status_code == 200 else []
                else:
                    r = await client.get(h.url)
                    rows = parse_homepage(r.text, str(r.url), by_src.get(src.name, [])) if r.status_code == 200 else []
            except httpx.HTTPError as e:
                tried.append(f"{h.kind} {type(e).__name__}")
                continue
            if rows:
                return src.name, [Headline(src.name, i, t, h.kind, u) for i, (t, u) in enumerate(rows, 1) if t], h.kind
            tried.append(f"{h.kind} {r.status_code if r.status_code != 200 else '없음'}")
        return src.name, [], " / ".join(tried) or "설정 없음"

    try:
        res = await asyncio.gather(*(one(s) for s in sources.sources if s.enabled and s.headline))
    finally:
        if own:
            await client.aclose()
    return [h for _, hs, _ in res for h in hs], {name: st for name, _, st in res}


def _bigrams(s: str) -> set[str]:
    s = "".join(ch for ch in s.lower() if ch.isalnum())
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _jac(a: str, b: str) -> float:
    x, y = _bigrams(a), _bigrams(b)
    return len(x & y) / len(x | y) if x | y else 0.0


LEX_MIN = 0.3        # 제목 글자 2-gram 자카드 (10/16자 1면 21건: 같은 기사 0.37~1.0, 다른 기사 0.05)
EMB_MIN = 0.90       # 또는 임베딩 유사도 + 2위와의 차이 (틀린 2건은 0.842·0.851, 2위와 차 0.01)
EMB_GAP = 0.03


def match(heads: list[Headline], day_articles: list[Article], vecs: np.ndarray | None = None, embed=None) -> None:
    """머리기사 → 같은 매체 그날 기사 (article_id, how 를 채운다). vecs: day_articles 임베딩, embed: 제목 → 벡터."""
    pos: dict[str, list[int]] = {}
    for i, a in enumerate(day_articles):
        pos.setdefault(a.source, []).append(i)
    url_ix = {norm_url(a.url): i for i, a in enumerate(day_articles)}
    need = []
    for h in heads:
        idx = pos.get(h.source, [])
        if not idx:
            continue
        if h.url and (i := url_ix.get(norm_url(h.url))) is not None and day_articles[i].source == h.source:
            h.article_id, h.how = day_articles[i].id, "url"
            continue
        lex = [(_jac(h.title, day_articles[i].title), i) for i in idx]
        best, bi = max(lex)
        if best >= LEX_MIN:
            h.article_id, h.how = day_articles[bi].id, "title"
        else:
            need.append((h, idx))
    if need and vecs is not None and embed is not None:
        hv = embed([h.title for h, _ in need])
        for (h, idx), v in zip(need, hv):
            cos = vecs[idx] @ v
            order = np.argsort(cos)[::-1]
            gap = cos[order[0]] - (cos[order[1]] if len(order) > 1 else 0)
            if cos[order[0]] >= EMB_MIN and gap >= EMB_GAP:
                h.article_id, h.how = day_articles[idx[order[0]]].id, "embed"


GROUP_COS = 0.90   # LLM 없이 묶을 때: 같은 언어 기사 임베딩 코사인 (10/16자: 같은 주제 0.891~0.954, 다른 주제 최고 0.892 → 보수적으로)

GROUP_PROMPT = """아래는 오늘 여러 언론사가 1면·머리기사로 올린 기사 제목이다(번호: 매체 | 제목).
같은 사건·같은 기사거리를 다룬 것끼리 묶어라. 예: 같은 날 증시 폭락을 다룬 서로 다른 분석 기사는 한 묶음.
같은 분야라도 사건이 다르면 따로 둔다(예: 전작권 협상과 북한 미사일 발사는 다른 묶음). 혼자인 것은 빼도 된다.
출력 형식: {{"groups": [[번호, 번호, ...], ...]}}
{data}"""


def group(heads: list[Headline], day_articles: list[Article], vecs: np.ndarray | None, ask=None) -> str:
    """기사와 맞춘 머리기사끼리 같은 기사거리를 묶는다 (h.group). ask(prompt) → dict|None 이면 LLM, 아니면 임베딩.
    돌려주는 값: 쓴 방법."""
    import json as _json

    hs = [h for h in heads if h.article_id]
    if len(hs) < 2:
        return "없음"
    groups: list[list[int]] | None = None
    how = "임베딩"
    if ask is not None:
        rows = [{"번호": k, "매체": h.source, "제목": h.title} for k, h in enumerate(hs)]
        res = ask(GROUP_PROMPT.format(data="<data>\n" + _json.dumps(rows, ensure_ascii=False) + "\n</data>"))
        if res and isinstance(res.get("groups"), list):
            groups = [[int(k) for k in g if isinstance(k, (int, str)) and str(k).isdigit() and int(k) < len(hs)]
                      for g in res["groups"] if isinstance(g, list)]
            how = "LLM"
    if groups is None and vecs is not None:
        pos = {a.id: i for i, a in enumerate(day_articles)}
        lang = {a.id: a.lang for a in day_articles}
        parent = list(range(len(hs)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for x in range(len(hs)):
            for y in range(x + 1, len(hs)):
                a, b = hs[x].article_id, hs[y].article_id
                if lang[a] == lang[b] and float(vecs[pos[a]] @ vecs[pos[b]]) >= GROUP_COS:
                    parent[find(x)] = find(y)
        by: dict[int, list[int]] = {}
        for k in range(len(hs)):
            by.setdefault(find(k), []).append(k)
        groups = list(by.values())
    for g, members in enumerate(groups or []):
        if len(members) >= 2:
            for k in members:
                hs[k].group = g
    return how if groups is not None else "없음"


def to_json(heads: list[Headline]) -> list[dict]:
    return [asdict(h) for h in heads]


def issue_headlines(heads: list[dict], issue_articles: list[str]) -> dict[str, list]:
    """이슈에 실린 매체 머리기사: 매체 → [가장 높은 순위, 얻은 곳(naver_a1/feed/homepage)].
    이 이슈의 기사가 든 기사거리 묶음(group)의 다른 매체 머리기사도 함께 센다 (매체마다 다른 기사로 같은 주제를 1면에 올림)."""
    ids = set(issue_articles)
    groups = {h["group"] for h in heads if h.get("article_id") in ids and h.get("group") is not None}
    out: dict[str, list] = {}
    for h in heads:
        mine = h.get("article_id") in ids or (h.get("group") is not None and h["group"] in groups and h.get("article_id"))
        if mine and (h["source"] not in out or h["rank"] < out[h["source"]][0]):
            out[h["source"]] = [h["rank"], h["via"]]
    return out


def group_members(heads: list[dict]) -> list[set[str]]:
    """기사거리 묶음별 기사 id 집합 (편집에서 같은 묶음 이슈를 한 기사로 합칠 때)."""
    by: dict[int, set[str]] = {}
    for h in heads:
        if h.get("group") is not None and h.get("article_id"):
            by.setdefault(h["group"], set()).add(h["article_id"])
    return list(by.values())
