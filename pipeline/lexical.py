"""어휘 겹침 유사도 (TF-IDF 코사인) — 임베딩만으로 가르지 못하는 같은 언어 기사 쌍을 보완한다.

- 같은 언어 비교용 "전체 토큰": 한글·한자·가나는 글자 2-gram(한자는 1글자도), 영문은 단어
- 다른 언어 비교용 "공통 단서": 언어와 무관하게 그대로 쓰이는 숫자(소수·%)와 영문 고유명사·약어
  (예: HBM, TSMC, Netflix, 3.7%). 한국어 기사에 섞인 영문 약어도 여기서 잡힌다.
"""
from __future__ import annotations

import math
import re
import unicodedata

import numpy as np
from scipy.sparse import csr_matrix

_HANGUL_RUN = re.compile(r"[가-힣]+")
_CJK_RUN = re.compile(r"[぀-ヿ一-鿿]+")
_HAN_CHAR = re.compile(r"[一-鿿]")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z\-']+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*\s?%?")

STOP_EN = set(
    """a an the and or but of to in on at for from by with as is are was were be been being it its this that these those
    after before over under about into than then there their they them he she his her we our you your not no will would
    can could may might says said say new more most up out off amid as how what why who when where which while just
    has have had do does did us""".split()
)


def _bigrams(run: str) -> list[str]:
    if len(run) == 1:
        return [run]
    return [run[i : i + 2] for i in range(len(run) - 1)]


def tokens(text: str) -> list[str]:
    out: list[str] = []
    for run in _HANGUL_RUN.findall(text):
        out += _bigrams(run)
    for run in _CJK_RUN.findall(text):
        out += _bigrams(run)
        out += _HAN_CHAR.findall(run)  # 尹·美·日 같은 한 글자 약칭
    for w in _LATIN_WORD.findall(text):
        w = w.lower().strip("-'")
        if len(w) >= 2 and w not in STOP_EN:
            out.append(w[:-1] if w.endswith("s") and len(w) > 3 else w)
    out += anchors(text)
    return out


def anchors(text: str) -> list[str]:
    """언어와 무관한 단서: 소수·% 가 붙은 숫자, 대문자로 시작하는 영문 단어·약어."""
    out = []
    text = unicodedata.normalize("NFKC", text)  # 전각 ％·숫자(일본어 기사)를 반각으로
    for n in _NUMBER.findall(text):
        n = n.replace(",", "").replace(" ", "")
        if "%" in n or "." in n or (n.isdigit() and len(n) >= 3 and not (1990 <= int(n) <= 2035)):
            out.append("#" + n)
    for w in _LATIN_WORD.findall(text):
        if w[0].isupper() and len(w) >= 2 and w.lower() not in STOP_EN:
            out.append("@" + re.sub(r"'s$", "", w.lower()))
    return out


def drop_source_templates(docs: list[list[str]], sources: list[str], min_docs: int = 3, share: float = 0.8) -> list[list[str]]:
    """한 매체 안에서만 반복되는 상투 토큰을 지운다.

    예: WSJ "… Roundup: Market Talk", 한겨레 "10월 16일 ○○ 새 책". 이런 토큰은 그날 전체로 보면 드물어
    IDF 가 높게 나오는 바람에 서로 다른 기사를 같은 사건처럼 보이게 만든다.
    기준: 같은 매체 문서 min_docs 개 이상에 나오고, 그 토큰이 나온 문서의 share 이상이 그 매체 것.
    """
    by_tok: dict[str, list[int]] = {}
    for i, toks in enumerate(docs):
        for t in set(toks):
            by_tok.setdefault(t, []).append(i)
    drop: dict[str, set[str]] = {}
    for t, ix in by_tok.items():
        if len(ix) < min_docs:
            continue
        counts: dict[str, int] = {}
        for i in ix:
            counts[sources[i]] = counts.get(sources[i], 0) + 1
        src, c = max(counts.items(), key=lambda kv: kv[1])
        if c >= min_docs and c / len(ix) >= share:
            drop.setdefault(src, set()).add(t)
    return [[t for t in toks if t not in drop.get(sources[i], ())] for i, toks in enumerate(docs)]


def tfidf_similarity(docs: list[list[str]]) -> np.ndarray:
    """토큰 목록들 → 쌍별 TF-IDF 코사인 유사도 (dense n×n)."""
    n = len(docs)
    vocab: dict[str, int] = {}
    df: dict[int, int] = {}
    rows, cols, vals = [], [], []
    for i, toks in enumerate(docs):
        counts: dict[int, int] = {}
        for t in toks:
            j = vocab.setdefault(t, len(vocab))
            counts[j] = counts.get(j, 0) + 1
        for j, c in counts.items():
            df[j] = df.get(j, 0) + 1
            rows.append(i)
            cols.append(j)
            vals.append(1 + math.log(c))
    if not vocab:
        return np.zeros((n, n), dtype=np.float32)
    idf = np.array([math.log((n + 1) / (df[j] + 1)) + 1 for j in range(len(vocab))], dtype=np.float32)
    x = csr_matrix((np.array(vals, dtype=np.float32) * idf[cols], (rows, cols)), shape=(n, len(vocab)))
    norms = np.sqrt(np.asarray(x.multiply(x).sum(axis=1)).ravel())
    norms[norms == 0] = 1
    x = csr_matrix(x.multiply(1 / norms[:, None]))
    return (x @ x.T).toarray().astype(np.float32)
