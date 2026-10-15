from pipeline.interest import build_interest_table
from pipeline.settings import TOPICS, load_interests


def table():
    return build_interest_table(load_interests())


def test_every_topic_has_weight():
    t = table()
    assert set(t.topic_weights) == set(TOPICS)


def test_interview_answers_applied():
    w = table().topic_weights
    # 선택한 4개 분야 = 1.0, 덜 볼 3개 분야 = 0.2, 나머지 = 0.5
    for topic in ("economy", "semis_ai", "politics", "international"):
        assert w[topic] == 1.0
    for topic in ("entertainment_sports", "incidents", "lifestyle_culture"):
        assert w[topic] == 0.2
    for topic in ("industry", "society", "science"):
        assert w[topic] == 0.5


def test_less_topics_never_zero():
    # 덜 볼 분야도 0이 아니어야 중요 뉴스가 다양성 슬롯 밖에서도 완전히 사라지지 않는다
    assert all(v > 0 for v in table().topic_weights.values())


def test_keyword_boost():
    t = table()
    plain = t.score("industry", "조선업 수주 증가")
    boosted = t.score("industry", "SK하이닉스, HBM 공급 확대")
    assert boosted == plain + 0.5
    # 대소문자 무시 (영문 키워드)
    assert t.score("industry", "hbm demand surges") == plain + 0.5
    # 키워드 여러 개여도 가산은 한 번
    assert t.score("industry", "삼성전자 SK하이닉스 엔비디아") == plain + 0.5
