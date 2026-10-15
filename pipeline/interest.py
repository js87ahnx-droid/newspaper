"""interests.yaml → 관심도 가중치 표.

편집 단계(S6)는 이 표만 보고 관심도를 매긴다. 1면 톱 선정에는 쓰지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass

from .settings import TOPICS, Interests


@dataclass(frozen=True)
class InterestTable:
    topic_weights: dict[str, float]   # 모든 분야에 값이 있다
    keywords: tuple[str, ...]
    keyword_boost: float

    def score(self, topic: str, text: str) -> float:
        """기사 하나의 관심도 원점수: 분야 가중치 + 키워드가 하나라도 나오면 가산."""
        base = self.topic_weights.get(topic, 0.0)
        lowered = text.lower()
        if any(k.lower() in lowered for k in self.keywords):
            base += self.keyword_boost
        return base


def build_interest_table(interests: Interests) -> InterestTable:
    weights = {}
    for topic in TOPICS:
        if topic in interests.topics:
            weights[topic] = interests.topics[topic]
        elif topic in interests.less:
            weights[topic] = interests.less_weight
        else:
            weights[topic] = interests.default_weight
    return InterestTable(weights, tuple(interests.keywords), interests.keyword_boost)
