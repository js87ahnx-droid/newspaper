"""논평·사설면 (2026-10-16 사용자 요청: "논평 사설도 별도로 추가 정리").

1. 같은 이슈, 다른 사설 — 지면에 실린 이슈를 성향이 다른 매체 둘 이상이 사설로 다뤘으면 나란히
2. 오늘의 사설 — 나머지 사설을 성향 순으로
3. 주요 칼럼·논평 — 지면 이슈와 이어진 칼럼 먼저, 그다음 매체 영향력 순 (상한 있음)

사설·칼럼과 이슈의 연결: 같은 언어 기사끼리 어휘 겹침(TF-IDF, 제목 + 리드)으로. 번역 없이 다른 언어는 잇지 않는다.
본문은 쓰지 않는다 — 제목·RSS 리드·링크만.
"""
from __future__ import annotations

import re

from .collect import Article
from .lexical import drop_source_templates, tfidf_similarity, tokens
from .stance import LEAN_ORDER, words

# 사설·칼럼 ↔ 지면 이슈 연결 최소 유사도 (10/16호 실측: 한국어 맞는 연결 0.13~0.56 / 틀린 연결 ≤0.10,
# 영어 맞는 연결 0.33~0.50 / 틀린 연결 ≤0.16). 하루치로 정한 값이라 시범 운영(S12)에서 재검증
LINK_MIN = {"ko": 0.12, "en": 0.20}
LINK_MIN_DEFAULT = 0.20
# 사설끼리 같은 주제로 묶는 최소 유사도 (같은 매체 사설끼리는 묶지 않는다). 10/16호: 같은 주제 쌍 ≥0.086, 다른 주제 ≤0.069
EDITORIAL_GROUP_MIN = 0.08
MAX_COLUMNS = 10


def _doc(a: Article) -> str:
    return f"{a.title} {a.lead[:200]}"


def common_words(day_articles: list[Article], ratio: float = 0.01) -> dict[str, set[str]]:
    """언어별 흔한 낱말: 그날 기사의 1% 넘게 나온 낱말 ("대통령", "결정" 같은 말은 연결 단서가 못 된다)."""
    out: dict[str, set[str]] = {}
    for lang in {a.lang for a in day_articles}:
        arts = [a for a in day_articles if a.lang == lang]
        df: dict[str, int] = {}
        for a in arts:
            for w in set(words(_doc(a), lang)):
                df[w] = df.get(w, 0) + 1
        cut = max(3, ratio * len(arts))
        out[lang] = {w for w, c in df.items() if c > cut}
    return out


def link_to_issues(opinions: list[Article], items: list[dict], common_by_lang: dict[str, set[str]] | None = None
                   ) -> dict[str, tuple[str, float]]:
    """의견 기사 id → (이슈 id, 유사도). 같은 언어 기사만 비교."""
    links: dict[str, tuple[str, float]] = {}
    for lang in {o.lang for o in opinions}:
        ops = [o for o in opinions if o.lang == lang]
        issue_docs, issue_ids = [], []
        for it in items:
            texts = [f"{a['title']} {a.get('lead', '')[:200]}" for a in it["articles"] if a.get("lang") == lang]
            if texts:
                issue_docs.append(" ".join(texts))
                issue_ids.append(it["issue_id"])
        if not ops or not issue_docs:
            continue
        docs = [tokens(_doc(o)) for o in ops] + [tokens(d) for d in issue_docs]
        sources = [o.source for o in ops] + ["__issue__"] * len(issue_docs)
        sim = tfidf_similarity(drop_source_templates(docs, sources))
        n = len(ops)
        issue_words = [set(words(d, lang)) for d in issue_docs]
        op_words = [set(words(_doc(o), lang)) for o in ops]
        # 흔한 낱말은 단서로 치지 않는다 (그날 기사 전체 기준, 없으면 지면·의견 글 기준 5%)
        if common_by_lang is not None:
            common = common_by_lang.get(lang, set())
        else:
            df: dict[str, int] = {}
            for ws in issue_words + op_words:
                for w in ws:
                    df[w] = df.get(w, 0) + 1
            common = {w for w, c in df.items() if c > max(3, 0.05 * len(issue_words + op_words))}
        for i, o in enumerate(ops):
            row = sim[i, n:]
            j = int(row.argmax())
            # 유사도 + 드문 낱말 두 개 이상 공유 ("생중계" 하나만 겹친 국무회의 칼럼 ↔ 트럼프 총살형 생중계 기사 같은 오연결 방지)
            if row[j] >= LINK_MIN.get(lang, LINK_MIN_DEFAULT) and len((op_words[i] & issue_words[j]) - common) >= 2:
                links[o.id] = (issue_ids[j], float(row[j]))
    return links


def group_editorials(editorials: list[Article]) -> list[list[Article]]:
    """같은 주제의 사설끼리 묶는다 (같은 언어, 다른 매체끼리만, 단일 연결). 지면 이슈와 무관하게 사설 사이에서 직접."""
    groups: list[list[Article]] = []
    for lang in sorted({e.lang for e in editorials}):
        eds = [e for e in editorials if e.lang == lang]
        if len(eds) < 2:
            continue
        sim = tfidf_similarity(drop_source_templates([tokens(_doc(e)) for e in eds], [e.source for e in eds]))
        parent = list(range(len(eds)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i in range(len(eds)):
            for j in range(i + 1, len(eds)):
                if eds[i].source != eds[j].source and sim[i, j] >= EDITORIAL_GROUP_MIN:
                    parent[find(i)] = find(j)
        by_root: dict[int, list[Article]] = {}
        for i, e in enumerate(eds):
            by_root.setdefault(find(i), []).append(e)
        groups += [g for g in by_root.values() if len(g) > 1]
    return groups


def _topic_label(eds: list[Article]) -> str:
    """지면 이슈와 이어지지 않은 사설 묶음의 이름: 대표 사설 제목에서 "[사설]" 표기를 뺀 것."""
    rep = max(eds, key=lambda e: (e.country == "KR", e.weight, len(e.lead)))
    return re.sub(r"\s*\[\s*사설\s*\]\s*", " ", rep.title).strip()


def _row(a: Article, link: tuple[str, float] | None, titles: dict[str, str]) -> dict:
    return {
        "id": a.id, "source": a.source, "lean": a.lean, "country": a.country, "lang": a.lang,
        "kind": a.opinion, "title": a.title, "lead": a.lead, "url": a.url, "paywall": a.paywall,
        "issue_id": link[0] if link else None, "issue_title": titles.get(link[0]) if link else None,
        "link_score": round(link[1], 3) if link else None,
    }


def organize(opinions: list[Article], edition: dict, day_articles: list[Article] | None = None) -> dict:
    items = [it for ps in edition["sections"].values() for it in ps]
    order = {it["issue_id"]: i for i, it in enumerate(items)}  # 지면 순서 = 대략 중요도 순
    titles = {it["issue_id"]: it["title"] for it in items}
    links = link_to_issues(opinions, items, common_words(day_articles) if day_articles else None)
    editorials = [o for o in opinions if o.opinion == "editorial"]
    columns = [o for o in opinions if o.opinion == "column"]

    # 1. 같은 주제, 다른 사설: 사설끼리 주제로 묶고, 같은 지면 이슈에 이어진 사설도 합친다
    groups = group_editorials(editorials)
    grouped = {e.id for g in groups for e in g}
    by_issue: dict[str, list[Article]] = {}
    for e in editorials:
        if e.id in links and e.id not in grouped:
            by_issue.setdefault(links[e.id][0], []).append(e)
    for g in groups:  # 묶음 안 사설이 이은 이슈가 있으면 그 이슈 이름을 쓴다
        iids = [links[e.id][0] for e in g if e.id in links]
        key = iids[0] if iids else "topic:" + g[0].id
        by_issue.setdefault(key, []).extend(g)
    compare = []
    used: set[str] = set()
    for key, eds in sorted(by_issue.items(), key=lambda kv: (order.get(kv[0], 999), kv[0])):
        leans = {e.lean for e in eds}
        if len(leans) < 2 or len({e.source for e in eds}) < 2:
            continue
        lean_groups = [{"lean": ln, "editorials": [_row(e, links.get(e.id), titles) for e in eds if e.lean == ln]}
                       for ln in LEAN_ORDER if ln in leans]
        on_page = key in titles
        compare.append({"issue_id": key if on_page else None,
                        "issue_title": titles[key] if on_page else _topic_label(eds),
                        "on_page": on_page, "groups": lean_groups})
        used.update(e.id for e in eds)

    # 2. 오늘의 사설 (비교에 안 쓴 것) — 성향 순, 같은 성향 안에서는 매체 영향력·이슈 순
    rest = [e for e in editorials if e.id not in used]
    rest.sort(key=lambda e: (LEAN_ORDER.index(e.lean) if e.lean in LEAN_ORDER else 9, e.country != "KR", -e.weight,
                             order.get(links.get(e.id, ("", 0))[0], 999), e.source))
    # 3. 주요 칼럼: 지면 이슈와 이어진 것 먼저 (이슈 순), 그다음 국내·영향력 순. 한 매체에서 최대 2편
    columns.sort(key=lambda c: (c.id not in links, order.get(links.get(c.id, ("", 0))[0], 999), c.country != "KR", -c.weight))
    picked, per_source = [], {}
    for c in columns:
        if per_source.get(c.source, 0) >= 2:
            continue
        picked.append(c)
        per_source[c.source] = per_source.get(c.source, 0) + 1
        if len(picked) >= MAX_COLUMNS:
            break
    return {
        "compare": compare,
        "editorials": [_row(e, links.get(e.id), titles) for e in rest],
        "columns": [_row(c, links.get(c.id), titles) for c in picked],
        "stats": {"editorials": len(editorials), "columns_total": len(columns), "columns_shown": len(picked),
                  "linked": sum(1 for o in opinions if o.id in links), "compare_issues": len(compare)},
    }
