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
MIN_TITLE = 12   # 이보다 짧은 제목은 기사가 아니라 메뉴·섹션 항목 (10/17 CNN "Business"·"Politics" 가 주소까지 같은 항목으로 수집돼 있었음)
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
    via: str                  # naver_a1 / feed / homepage / naver_page (S47: 신문 A2~A6면 — 지면 비중에만 씀)
    url: str | None = None
    article_id: str | None = None
    how: str | None = None    # 맞춘 방법: url / title / embed (못 맞추면 None)
    group: int | None = None  # 같은 기사거리(여러 매체가 각자 다른 기사로 1면에 올린 같은 주제) 번호
    page: str | None = None   # 신문 면 ("A1"·"A3") — naver_a1·naver_page 만 (S47)
    weight: float | None = None   # 그 신문의 매체 가중치 (sources.yaml) — 지면 비중 점수에 (S47)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG.sub("", html))).strip()


def norm_url(u: str) -> str:
    s = urlsplit(u)
    host = s.netloc.lower().removeprefix("www.").removeprefix("m.")
    return (host + s.path).rstrip("/").lower()


def parse_naver_a1(html: str) -> list[str]:
    m = _A1.search(html)
    return [_text(t) for t in _STRONG.findall(m.group(2))][:TOP_N] if m else []


# S47: 같은 페이지의 A섹션(또는 번호만 있는 면) 1~6면 — 신문이 한 이슈에 몇 면을 썼는지 (지면 비중)
_PAGE = re.compile(r'<em>(A?)(\d+)</em>면</span></h3>\s*<ul class="newspaper_article_lst">(.*?)</ul>', re.S)
PAGE_MAX = 6


def parse_naver_pages(html: str) -> list[tuple[str, int, str]]:
    """[(면 "A1"~"A6", 그 면 안 순서, 제목)]. "1면"·"A1" 은 모두 A1, B·C·E 섹션은 읽지 않는다."""
    out = []
    for m in _PAGE.finditer(html):
        n = int(m.group(2))
        if 1 <= n <= PAGE_MAX:
            out += [(f"A{n}", k, t) for k, t in enumerate((_text(x) for x in _STRONG.findall(m.group(3))), 1) if t]
    return out


def parse_feed(xml: bytes) -> list[tuple[str, str]]:
    import feedparser

    return [(e.get("title", "").strip(), e.get("link", "")) for e in feedparser.parse(xml).entries[:TOP_N]]


def parse_homepage(html: str, base: str, arts: list[Article]) -> list[tuple[str, str]]:
    """홈페이지 링크를 순서대로 보며 그 매체의 그날 기사와 맞는 첫 TOP_N 건 (주소가 같거나 링크 글이 제목과 같음)."""
    arts = [a for a in arts if len(title_key(a.title)) >= MIN_TITLE]
    urls = {norm_url(a.url): a for a in arts}
    titles = {title_key(a.title)[:24]: a for a in arts}
    out, seen = [], set()
    for href, inner in _ANCHOR.findall(html):
        text = _text(inner)
        key = title_key(text)[:24]
        a = urls.get(norm_url(urljoin(base, href))) or (titles.get(key) if len(key) >= MIN_TITLE else None)
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
            pages: list[Headline] = []
            try:
                if h.kind == "naver_a1":
                    r = await client.get(f"https://media.naver.com/press/{h.press}/newspaper", params={"date": edition.strftime("%Y%m%d")})
                    rows = [(t, None) for t in parse_naver_a1(r.text)] if r.status_code == 200 else []
                    if rows:   # S47: 같은 페이지의 A2~A6면 (지면 비중). 머리기사 경로(묶음·1면 표시)에는 안 들어간다
                        pages = [Headline(src.name, k, t, "naver_page", page=pg, weight=src.weight)
                                 for pg, k, t in parse_naver_pages(r.text) if pg != "A1"]
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
                heads = [Headline(src.name, i, t, h.kind, u, page="A1" if h.kind == "naver_a1" else None)
                         for i, (t, u) in enumerate(rows, 1) if t]
                return src.name, heads + pages, h.kind
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
PAGE_CROSS_LEX = 0.5   # S47: 신문 A2~A6면 제목을 다른 매체 기사와 맞출 때 — 같은 매체(0.3)보다 엄하게
PAGE_CROSS_EMB = 0.93  # 다른 매체로 임베딩 맞출 때: 같은 사건 기사가 여럿이라 2위와 차이는 안 보고, 대신 기준을 올린다 (S47 리뷰)


def match(heads: list[Headline], day_articles: list[Article], vecs: np.ndarray | None = None, embed=None) -> None:
    """머리기사 → 같은 매체 그날 기사 (article_id, how 를 채운다). vecs: day_articles 임베딩, embed: 제목 → 벡터."""
    pos: dict[str, list[int]] = {}
    for i, a in enumerate(day_articles):
        if len(title_key(a.title)) >= MIN_TITLE:
            pos.setdefault(a.source, []).append(i)
    url_ix = {norm_url(a.url): i for i, a in enumerate(day_articles)}
    ko = [i for i, a in enumerate(day_articles) if a.lang == "ko" and len(title_key(a.title)) >= MIN_TITLE]
    need = []
    for h in heads:
        idx = pos.get(h.source, [])
        if len(title_key(h.title)) < MIN_TITLE:
            continue
        if h.via == "naver_page":
            # S47: 신문 A2~A6면 제목 — 같은 신문 기사 먼저, 없으면 그날 국내 기사 전체에서 (그 신문 온라인 기사가 수집에 없는 날이 많다)
            own = [(_jac(h.title, day_articles[i].title), i) for i in idx]
            best, bi = max(own, default=(0.0, -1))
            if best >= LEX_MIN:
                h.article_id, h.how = day_articles[bi].id, "title"
                continue
            cross = max(((_jac(h.title, day_articles[i].title), i) for i in ko), default=(0.0, -1))
            if cross[0] >= PAGE_CROSS_LEX:
                h.article_id, h.how = day_articles[cross[1]].id, "title-cross"
            else:
                need.append((h, ko))
            continue
        if not idx:
            continue
        if h.url and (i := url_ix.get(norm_url(h.url))) is not None and i in idx:
            h.article_id, h.how = day_articles[i].id, "url"
            continue
        lex = [(_jac(h.title, day_articles[i].title), i) for i in idx]
        best, bi = max(lex)
        if best >= LEX_MIN:
            h.article_id, h.how = day_articles[bi].id, "title"
        else:
            need.append((h, idx))
    need = [(h, idx) for h, idx in need if idx]   # 맞출 기사가 없으면 건너뜀 (S47 리뷰: 빈 목록이면 order[0] 오류)
    if need and vecs is not None and embed is not None:
        hv = embed([h.title for h, _ in need])
        for (h, idx), v in zip(need, hv):
            cos = vecs[idx] @ v
            order = np.argsort(cos)[::-1]
            gap = cos[order[0]] - (cos[order[1]] if len(order) > 1 else 0)
            # 다른 매체로 맞출 때는 같은 사건 기사가 여럿이라 2위와 차이가 작다 — 그 기준은 같은 매체 안에서만 (S47)
            if (cos[order[0]] >= EMB_MIN and gap >= EMB_GAP) if h.via != "naver_page" else cos[order[0]] >= PAGE_CROSS_EMB:
                h.article_id, h.how = day_articles[idx[order[0]]].id, "embed" if h.via != "naver_page" else "embed-cross"


GROUP_COS = 0.90   # LLM 없이 묶을 때: 같은 언어 기사 임베딩 코사인 (10/16자: 같은 주제 0.891~0.954, 다른 주제 최고 0.892 → 보수적으로)

GROUP_PROMPT = """아래는 오늘 여러 언론사가 1면·머리기사로 올린 기사 제목이다(번호, 매체, 제목).
같은 사건·같은 기사거리를 다룬 것이 확실한 것끼리만 묶어라. 예: 같은 날 증시 폭락을 다룬 서로 다른 분석 기사는 한 묶음,
같은 인물 경질을 다룬 한국어·영어 기사는 한 묶음. 같은 분야·같은 나라라도 사건이 다르면 묶지 않는다
(예: 전작권 협상과 북한 미사일 발사, 백악관 대변인 경질과 러시아 제재 완화는 각각 다른 묶음). 조금이라도 애매하면 묶지 말고,
혼자인 것은 출력하지 않는다.
출력 형식: {{"groups": [[번호, 번호, ...], ...]}}
{data}"""


def group(heads: list[Headline], day_articles: list[Article], vecs: np.ndarray | None, ask=None) -> str:
    """기사와 맞춘 머리기사끼리 같은 기사거리를 묶는다 (h.group). ask(prompt) → dict|None 이면 LLM, 아니면 임베딩.
    돌려주는 값: 쓴 방법."""
    import json as _json

    hs = [h for h in heads if h.article_id and h.via != "naver_page"]   # S47: 지면 비중 줄은 기사거리 묶음에 안 넣는다
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
    heads = [h for h in heads if h.get("via") != "naver_page"]   # S47: 지면 비중 줄은 issue_pages 로만
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
        if h.get("group") is not None and h.get("article_id") and h.get("via") != "naver_page":
            by.setdefault(h["group"], set()).add(h["article_id"])
    return list(by.values())


def issue_pages(heads: list[dict], issue_articles: list[str], a1_sources: set[str] = frozenset()) -> dict[str, str]:
    """이슈를 A2~A6면에 실은 국내 신문: 신문 → 가장 앞 면 (S47 지면 비중). a1_sources(이 이슈를 직접 A1 에 실은 신문)는 뺀다."""
    ids = set(issue_articles)
    out: dict[str, str] = {}
    for h in heads:
        if h.get("via") != "naver_page" or h.get("article_id") not in ids or h["source"] in a1_sources:
            continue
        pg = h.get("page") or "A9"
        if h["source"] not in out or int(pg[1:]) < int(out[h["source"]][1:]):
            out[h["source"]] = pg
    return out
