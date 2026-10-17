"""3단계 이슈 묶기: 다국어 임베딩(로컬 CPU, 무토큰) + 어휘 겹침 + 계층적 군집.

같은 사건을 다룬 한·영·일 기사를 한 이슈로 묶는다. 모델 파일은 처음 한 번 내려받아
models/ 에 캐시하고, 이후 실행은 네트워크 없이 돈다.

유사도 (S5 검수 1차 불합격 뒤 설계, docs-internal/cluster-review-round1.md):
- 같은 언어 쌍:  (1 - w)·임베딩 + w·어휘 TF-IDF        — 임베딩만으로는 "같은 분야"와 "같은 사건"을 못 가른다
- 다른 언어 쌍:  임베딩 + b·공통 단서 TF-IDF (숫자·영문 고유명사) — 번역돼도 그대로 남는 단서를 가산
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from .collect import Article
from .lexical import drop_source_templates, tfidf_similarity, tokens
from .settings import ROOT, Clustering

MODEL_ALIASES = {
    "paraphrase-multilingual-MiniLM-L12-v2": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "multilingual-e5-large": "intfloat/multilingual-e5-large",
    "potion-multilingual-128M": "minishlab/potion-multilingual-128M",
}
# e5 계열은 입력 앞에 용도 표시를 붙여야 한다 (대칭 유사도 비교는 "query: ")
MODEL_PREFIX = {"intfloat/multilingual-e5-large": "query: "}
EMBED_LEAD_CHARS = 120  # 제목 + 리드 앞부분만 쓴다 (리드 뒷부분은 배경 설명이라 군집을 흐린다)


@dataclass
class Issue:
    id: str
    article_ids: list[str]
    title: str                 # 대표 제목
    rep_article: str           # 대표 기사 id
    sources: list[str]
    countries: list[str]
    leans: list[str]
    langs: list[str]
    cohesion: float            # 묶인 기사들의 평균 유사도 (1개짜리는 1.0)
    extra: dict = field(default_factory=dict)


def embed_texts(texts: list[str], model: str, cache_dir: Path | None = None) -> np.ndarray:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from fastembed import TextEmbedding

    cache = cache_dir or ROOT / "models"
    name = MODEL_ALIASES.get(model, model)
    emb = TextEmbedding(model_name=name, cache_dir=str(cache), threads=os.cpu_count())
    prefix = MODEL_PREFIX.get(name, "")
    vecs = np.array(list(emb.embed([prefix + t for t in texts], batch_size=32)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.clip(norms, 1e-12, None)


def center_by_lang(vecs: np.ndarray, langs: list[str]) -> np.ndarray:
    """언어별 평균 벡터를 빼고 다시 정규화한다.

    다국어 임베딩은 같은 언어 문장끼리 내용과 무관하게 비슷하게 나오는 쏠림이 있다
    (실측: 한국어 쌍 평균 0.30, 영어 0.16). 그날 기사의 언어별 평균을 빼면 이 쏠림이 사라져
    무관한 기사가 한 덩어리로 묶이지 않고, 언어 간 비교도 공정해진다.
    """
    out = vecs.astype(np.float32, copy=True)
    arr = np.array(langs)
    for lg in set(langs):
        ix = arr == lg
        if ix.sum() >= 5:  # 기사가 너무 적은 언어는 평균이 곧 기사 자체라 빼지 않는다
            out[ix] -= out[ix].mean(axis=0)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.clip(norms, 1e-12, None)


def article_text(a: Article) -> str:
    return f"{a.title}. {a.lead[:EMBED_LEAD_CHARS]}".strip()


def csls_matrix(raw_vecs: np.ndarray, langs: np.ndarray, k: int = 10) -> np.ndarray:
    """CSLS(x, y) = 2·cos(x, y) − r_x(L_y) − r_y(L_x).

    r_x(L) 는 x 와 언어 L 기사들 중 가장 가까운 k 개의 평균 유사도. 어떤 기사와도 두루 비슷한 기사
    ("AI 시장" 같은 넓은 주제 기사, 쏠림이 큰 언어쌍)의 점수를 깎아, 두 기사가 서로에게만 특별히
    가까울 때 높게 나온다. (이중언어 사전 유도에서 쓰는 hubness 보정)
    """
    s = raw_vecs @ raw_vecs.T
    n = len(s)
    r = {}
    for lg in set(langs.tolist()):
        cols = np.where(langs == lg)[0]
        sub = s[:, cols].copy()
        own = np.isin(np.arange(n), cols)
        sub[np.where(own)[0], np.searchsorted(cols, np.where(own)[0])] = -np.inf  # 자기 자신 제외
        kk = max(1, min(k, len(cols) - 1))
        r[lg] = np.sort(sub, axis=1)[:, -kk:].mean(axis=1)
    rx = np.stack([r[lg] for lg in langs], axis=1)  # rx[i, j] = r_i(L_j)
    return 2 * s - rx - rx.T


def similarity_matrix(articles: list[Article], raw_vecs: np.ndarray, params: Clustering) -> np.ndarray:
    """쌍별 유사도. raw_vecs 는 중심화하지 않은 정규화 임베딩.

    - 같은 언어: 언어별 중심화 임베딩과 어휘 TF-IDF 의 가중 평균
    - 다른 언어: CSLS 점수가 cross_lang_csls_min 에 이르면 군집 문턱(similarity_threshold)에 닿도록 옮긴 값.
      원 점수만으로는 맞는 쌍(0.80~0.90)과 틀린 쌍(0.78~0.85)이 겹치고, 흔한 약어(AI·SNS·FIFA)를
      단서로 가산하면 오히려 틀린 쌍이 붙었다 (S5 검수 기록 참고)
    """
    texts = [article_text(a) for a in articles]
    sources = [a.source for a in articles]
    langs = np.array([a.lang for a in articles])
    centered = center_by_lang(raw_vecs, langs.tolist())
    emb_same = centered @ centered.T
    lex = tfidf_similarity(drop_source_templates([tokens(t) for t in texts], sources))
    same = langs[:, None] == langs[None, :]
    w = params.lexical_weight
    if same.all():
        s = (1 - w) * emb_same + w * lex
    else:
        # 언어별 추가 문턱: 그 언어가 낀 쌍은 max(기본, 언어별) 을 쓴다 (예: 기사 수가 적은 일본어)
        need = np.full(len(langs), params.cross_lang_csls_min, dtype=np.float32)
        for lg, m in params.csls_min_by_lang.items():
            need[langs == lg] = max(params.cross_lang_csls_min, m)
        pair_min = np.maximum(need[:, None], need[None, :])
        cross = csls_matrix(raw_vecs, langs, params.csls_k) - pair_min + params.similarity_threshold
        s = np.where(same, (1 - w) * emb_same + w * lex, cross)
    s = np.clip(s, -1, 1)
    np.fill_diagonal(s, 1)
    return s.astype(np.float32)


def cluster_similarity(sim: np.ndarray, threshold: float, method: str = "average") -> np.ndarray:
    """유사도 행렬 → 군집 번호 배열. 군집 간 (method 기준) 유사도가 threshold 이상이면 합친다."""
    n = len(sim)
    if n == 0:
        return np.array([], dtype=int)
    if n == 1:
        return np.array([1])
    sym = (sim + sim.T) / 2
    dist = squareform(np.clip(1 - sym, 0, 2), checks=False)
    z = linkage(dist, method=method)
    return fcluster(z, t=1 - threshold, criterion="distance")


def cluster_vectors(vecs: np.ndarray, threshold: float, method: str = "average") -> np.ndarray:
    return cluster_similarity(vecs @ vecs.T, threshold, method)


def representative(arts: list[Article], centrality: list[float] | None = None) -> Article:
    """대표 기사: 국내 매체 중 영향력 최고, 같은 영향력이면 묶음 중심에 가까운 기사.
    국내 기사가 없으면 묶음 중심에 가장 가까운 기사 (소수 기사가 대표가 되지 않게)."""
    cent = centrality or [0.0] * len(arts)
    idx = list(range(len(arts)))
    kr = [i for i in idx if arts[i].country == "KR" and arts[i].lang == "ko"]
    if kr:
        best = max(kr, key=lambda i: (arts[i].weight, round(cent[i], 2), arts[i].main, bool(arts[i].lead), -_ts(arts[i])))
    else:
        best = max(idx, key=lambda i: (round(cent[i], 2), arts[i].weight, -_ts(arts[i])))
    return arts[best]


def _ts(a: Article) -> float:
    return datetime.fromisoformat(a.published).timestamp() if a.published else 0.0


def build_issues(articles: list[Article], sim: np.ndarray, threshold: float, method: str = "average") -> list[Issue]:
    labels = cluster_similarity(sim, threshold, method)
    groups: dict[int, list[int]] = {}
    for i, lab in enumerate(labels):
        groups.setdefault(int(lab), []).append(i)
    issues = []
    for idx in groups.values():
        arts = [articles[i] for i in idx]
        sub = sim[np.ix_(idx, idx)]
        k = len(idx)
        if k > 1:
            cohesion = float((sub.sum() - k) / (k * (k - 1)))
            centrality = [float((sub[r].sum() - 1) / (k - 1)) for r in range(k)]
        else:
            cohesion, centrality = 1.0, [1.0]
        rep = representative(arts, centrality)
        uniq = lambda xs: sorted(set(xs))  # noqa: E731
        issues.append(
            Issue(
                id=rep.id,
                article_ids=[a.id for a in arts],
                title=rep.title,
                rep_article=rep.id,
                sources=uniq(a.source for a in arts),
                countries=uniq(a.country for a in arts),
                leans=uniq(a.lean for a in arts),
                langs=uniq(a.lang for a in arts),
                cohesion=round(cohesion, 3),
            )
        )
    issues.sort(key=lambda s: (-len(s.sources), -len(s.article_ids)))
    return issues


def mark_near(issues: list[Issue], articles: list[Article], sim: np.ndarray, mean_min: float, max_min: float,
              prefilter: float = 0.25) -> int:
    """같은 사건으로 보이는 이웃 이슈를 issue.extra["near"] 에 적는다. 돌려주는 값: 이웃 쌍 수.
    군집(평균 연결)이 합치지 않은 두 이슈라도 기사 쌍 평균이 mean_min 이상이거나, 같은 언어 기사끼리 가장 가까운 쌍이
    max_min 이상이면 같은 사건으로 본다.
    10/16호 실측(다매체 이웃 70쌍 검수): 평균 0.36 이상은 같은 사건·같은 흐름이 대부분(틀림 1건), 0.33~0.36 의 다른 언어 쌍은
    무관한 기사가 많았다(인도 배 전복↔파키스탄 학교 등). 가장 가까운 쌍 규칙은 다른 언어에서 단건 기사가 이웃 수십 개를
    갖는 쏠림이 생겨 같은 언어로 한정 (코스피 급락 속보 묶음들 0.59~0.64). 놓치는 것: 다른 언어 같은 사건 중 평균이 낮은 쌍
    (포트후드 0.342, 신압록강대교 0.328)."""
    pos = {a.id: i for i, a in enumerate(articles)}
    member = np.zeros((len(issues), len(articles)), dtype=np.float32)
    for r, iss in enumerate(issues):
        cols = [pos[x] for x in iss.article_ids]
        member[r, cols] = 1.0 / len(cols)
    mean = member @ sim.astype(np.float32) @ member.T
    pairs = 0
    for r, c in zip(*np.nonzero(np.triu(mean, 1) >= prefilter)):
        near = mean[r, c] >= mean_min
        if not near:
            ia = [pos[x] for x in issues[r].article_ids]
            ib = [pos[x] for x in issues[c].article_ids]
            la = np.array([articles[i].lang for i in ia])
            lb = np.array([articles[i].lang for i in ib])
            same = la[:, None] == lb[None, :]
            near = bool(same.any()) and float(sim[np.ix_(ia, ib)][same].max()) >= max_min
        if near:
            issues[r].extra.setdefault("near", []).append(issues[c].id)
            issues[c].extra.setdefault("near", []).append(issues[r].id)
            pairs += 1
    return pairs


def issues_to_json(issues: list[Issue]) -> list[dict]:
    return [asdict(i) for i in issues]
