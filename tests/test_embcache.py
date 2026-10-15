import numpy as np

import pipeline.embcache as ec
from pipeline.collect import Article


def art(id, title):
    return Article(
        id=id, url=f"https://x.test/{id}", source="A", country="KR", lean="중도", media_type="종합지", weight=1.0,
        paywall=False, kind="rss", title=title, lead="", lang="ko", published="2026-10-15T12:00:00+00:00",
        date_source="feed", sections=["top"], main=False, first_seen="2026-10-15T12:00:00+00:00",
    )


def fake_embed(texts, model):
    fake_embed.calls += len(texts)
    return np.array([[len(t), 1.0] for t in texts], dtype=np.float32)


fake_embed.calls = 0


def test_fill_only_missing_and_persist(tmp_path, monkeypatch):
    monkeypatch.setattr(ec, "embed_texts", fake_embed)
    fake_embed.calls = 0
    path = tmp_path / "emb.npz"
    a, b = art("a", "가"), art("b", "나다")
    c = ec.EmbeddingCache(path)
    assert c.fill([a], "m") == 1
    c2 = ec.EmbeddingCache(path)  # 디스크에서 다시 읽기
    assert c2.fill([a, b], "m") == 1  # a 는 이미 있음
    assert fake_embed.calls == 2
    assert c2.get([b, a]).shape == (2, 2)


def test_text_change_recomputes(tmp_path, monkeypatch):
    monkeypatch.setattr(ec, "embed_texts", fake_embed)
    c = ec.EmbeddingCache(tmp_path / "emb.npz")
    a = art("a", "원래 제목")
    c.fill([a], "m")
    a.title = "고친 제목"
    assert c.missing([a]) == [a]


def test_prune(tmp_path, monkeypatch):
    monkeypatch.setattr(ec, "embed_texts", fake_embed)
    c = ec.EmbeddingCache(tmp_path / "emb.npz")
    a, b = art("a", "가"), art("b", "나")
    c.fill([a, b], "m")
    assert c.prune([a]) == 1
    c.save()
    assert ec.EmbeddingCache(tmp_path / "emb.npz").missing([a, b]) == [b]
