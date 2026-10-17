import numpy as np

from pipeline.cluster import build_issues, cluster_vectors, representative
from pipeline.collect import Article


def art(id, source, country="KR", lang="ko", weight=1.0, main=False, lead="리드", published="2026-10-15T12:00:00+00:00"):
    return Article(
        id=id, url=f"https://x.test/{id}", source=source, country=country, lean="중도", media_type="종합지",
        weight=weight, paywall=False, kind="rss", title=f"{source} 제목 {id}", lead=lead, lang=lang,
        published=published, date_source="feed", sections=["top"], main=main, first_seen=published,
    )


def unit(*v):
    v = np.array(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_cluster_vectors_groups_similar():
    vecs = np.stack([unit(1, 0, 0), unit(0.95, 0.05, 0), unit(0, 1, 0), unit(0.02, 0.98, 0), unit(0, 0, 1)])
    labels = cluster_vectors(vecs, threshold=0.9)
    assert labels[0] == labels[1]
    assert labels[2] == labels[3]
    assert len({labels[0], labels[2], labels[4]}) == 3


def test_threshold_controls_merging():
    vecs = np.stack([unit(1, 0), unit(0.8, 0.6)])  # 코사인 0.8
    assert len(set(cluster_vectors(vecs, 0.75))) == 1
    assert len(set(cluster_vectors(vecs, 0.85))) == 2


def test_edge_sizes():
    assert len(cluster_vectors(np.zeros((0, 3)), 0.6)) == 0
    assert list(cluster_vectors(np.stack([unit(1, 0)]), 0.6)) == [1]


def test_csls_penalizes_hub():
    """두루 비슷한 '허브' 기사와의 쌍보다 서로에게만 가까운 쌍이 높게 나온다."""
    from pipeline.cluster import csls_matrix

    rng = np.random.default_rng(0)
    base = rng.normal(size=(6, 8))
    ko = base / np.linalg.norm(base, axis=1, keepdims=True)
    en = ko + rng.normal(scale=0.05, size=ko.shape)  # 각 한국어 기사의 영어 짝
    hub = ko.mean(axis=0, keepdims=True)              # 모든 한국어 기사와 비슷한 영어 기사
    vecs = np.vstack([ko, en, hub])
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    langs = np.array(["ko"] * 6 + ["en"] * 7)
    c = csls_matrix(vecs, langs, k=2)
    for i in range(6):
        assert c[i, 6 + i] > c[i, 12]  # 진짜 짝 > 허브


def test_representative_prefers_korean_heavy_main():
    arts = [
        art("a", "BBC", country="UK", lang="en", weight=1.0, main=True),
        art("b", "한겨레", weight=0.9, main=True),
        art("c", "연합뉴스", weight=1.0, main=False),
        art("d", "조선일보", weight=1.0, main=True),
    ]
    assert representative(arts).id == "d"
    # 국내 기사가 없으면 전체에서
    assert representative([arts[0], art("e", "Fox", country="US", lang="en", weight=0.8)]).id == "a"


def test_build_issues_fields():
    arts = [art("a", "조선일보"), art("b", "BBC", country="UK", lang="en"), art("c", "NHK", country="JP", lang="ja")]
    vecs = np.stack([unit(1, 0), unit(0.97, 0.03), unit(0, 1)])
    issues = build_issues(arts, vecs @ vecs.T, threshold=0.9)
    assert len(issues) == 2
    top = issues[0]
    assert sorted(top.article_ids) == ["a", "b"]
    assert top.countries == ["KR", "UK"] and top.langs == ["en", "ko"]
    assert top.title == "조선일보 제목 a"
    assert 0.9 < top.cohesion <= 1.0


def test_mark_near_mean_or_same_language_max():
    import numpy as np

    from pipeline.cluster import Issue, mark_near

    def a(i, lang):
        return Article(id=f"a{i}", url=f"https://x/{i}", source=f"S{i}", country="KR", lean="중도", media_type="종합지",
                       weight=1.0, paywall=False, kind="rss", title="t", lead="", lang=lang, published="2026-10-15T12:00:00+00:00",
                       date_source="feed", sections=["top"], first_seen="2026-10-15T12:00:00+00:00")

    arts = [a(0, "ko"), a(1, "ko"), a(2, "en"), a(3, "en"), a(4, "ko"), a(5, "en")]
    sim = np.eye(6)
    sim[0, 4] = sim[4, 0] = 0.6    # 같은 언어 가장 가까운 쌍 0.6 → 이웃
    sim[1, 2] = sim[2, 1] = 0.37   # 다른 언어, 평균 0.37 → 이웃
    sim[3, 5] = sim[5, 3] = 0.3    # 0.3 → 이웃 아님
    iss = [Issue(id=f"i{k}", article_ids=[f"a{k}"], title="t", rep_article=f"a{k}", sources=[], countries=[], leans=[],
                 langs=[], cohesion=1.0) for k in range(6)]
    assert mark_near(iss, arts, sim, mean_min=0.36, max_min=0.55) == 2
    assert iss[0].extra["near"] == ["i4"] and iss[1].extra["near"] == ["i2"] and "near" not in iss[3].extra
