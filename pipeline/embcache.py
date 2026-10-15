"""기사 임베딩 캐시 — e5-large 는 CPU에서 느리므로(이 PC 기준 기사당 약 1.8초) 수집할 때마다
새 기사만 임베딩해 쌓아 두고, 발행 때는 캐시를 읽기만 한다.

임베딩 입력(article_text)이 바뀌면 같은 id 라도 다시 계산하도록 입력 문자열의 해시를 함께 저장한다.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from .cluster import article_text, embed_texts
from .collect import Article


def _key(a: Article) -> str:
    return hashlib.sha1(article_text(a).encode()).hexdigest()[:16]


class EmbeddingCache:
    def __init__(self, path: Path):
        self.path = path
        self.vecs: dict[str, np.ndarray] = {}
        if path.exists():
            data = np.load(path, allow_pickle=False)
            for k, v in zip(data["keys"], data["vecs"]):
                self.vecs[str(k)] = v

    def missing(self, articles: list[Article]) -> list[Article]:
        return [a for a in articles if _key(a) not in self.vecs]

    def fill(self, articles: list[Article], model: str, batch: int = 64) -> int:
        """없는 것만 계산해 채운다. 계산한 수를 돌려준다. batch 개마다 저장해 중간에 끊겨도 진척이 남는다."""
        todo = self.missing(articles)
        for start in range(0, len(todo), batch):
            chunk = todo[start : start + batch]
            vecs = embed_texts([article_text(a) for a in chunk], model)
            for a, v in zip(chunk, vecs):
                self.vecs[_key(a)] = v
            self.save()
        return len(todo)

    def get(self, articles: list[Article]) -> np.ndarray:
        return np.stack([self.vecs[_key(a)] for a in articles])

    def prune(self, keep: list[Article]) -> int:
        want = {_key(a) for a in keep}
        drop = [k for k in self.vecs if k not in want]
        for k in drop:
            del self.vecs[k]
        return len(drop)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        keys = np.array(list(self.vecs), dtype="U16")
        vecs = np.stack(list(self.vecs.values())) if self.vecs else np.zeros((0, 1), dtype=np.float32)
        tmp = self.path.with_name(self.path.stem + ".tmp.npz")
        np.savez(tmp, keys=keys, vecs=vecs.astype(np.float32))
        tmp.replace(self.path)
