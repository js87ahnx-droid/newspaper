import numpy as np

from pipeline.lexical import anchors, tfidf_similarity, tokens


def test_korean_bigrams_and_han_chars():
    t = tokens("尹 영치금 19억")
    assert "영치" in t and "치금" in t and "尹" in t


def test_english_words_stopwords_plural():
    t = tokens("The Netflix cuts jobs")
    assert "netflix" in t and "cut" in t and "job" in t and "the" not in t


def test_anchors_numbers_and_proper_nouns():
    a = anchors("TSMC 3분기 순이익 69% 급증, HBM 공급 2026년 1,000명")
    assert "@tsmc" in a and "@hbm" in a and "#69%" in a and "#1000" in a
    assert "#2026" not in a  # 연도는 단서가 아님
    assert "@boss" in anchors("Boss resigns")  # 끝 s 를 잘못 깎지 않는다
    assert "#3.7%" in anchors("米 9月の消費者物価 3.7％上昇")  # 전각 ％


def test_cross_language_anchor_overlap():
    docs = [anchors("TSMC 3분기 순이익 69% 급증"), anchors("TSMC profit soars 69% in record quarter"), anchors("코스피 급락")]
    s = tfidf_similarity(docs)
    assert s[0, 1] > 0.9
    assert s[0, 2] == 0


def test_tfidf_same_event_vs_same_field():
    docs = [
        tokens("넷플릭스, 직원 1000명 감원…2022년 이후 최대"),
        tokens("넷플릭스 1000명 해고, 성장 둔화"),
        tokens("디즈니 크루즈 신규 여행 상품 출시"),
    ]
    s = tfidf_similarity(docs)
    assert s[0, 1] > s[0, 2]
    assert np.allclose(np.diag(s), 1, atol=1e-5)


def test_empty_docs():
    s = tfidf_similarity([[], []])
    assert s.shape == (2, 2) and not s.any()
