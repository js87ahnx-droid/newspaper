"""S51 큐레이션 판 다듬기 — 11/17 호 피드백 8가지."""
from __future__ import annotations

from pipeline.render import related_opinions
from pipeline.textutil import fix_kana_tree, kana_to_hangul, opinion_key


# ---------- S51a 사설·칼럼 중복 (⑧) ----------
def test_opinion_key_same_piece_two_feeds():
    a = opinion_key("Wall Street Journal", "Opinion | Can Nvidia Thrive Without Jensen Huang?")
    b = opinion_key("Wall Street Journal", "Can Nvidia Thrive Without  Jensen Huang?")
    assert a == b
    assert opinion_key("Bloomberg", "Can Nvidia Thrive Without Jensen Huang?") != a   # 다른 매체는 다른 글


def test_related_opinions_dedupe_by_source_title():
    op = {"editorials": [], "columns": [
        {"issue_id": "X", "source": "Wall Street Journal", "kind": "column", "title": "Opinion | Can Nvidia Thrive Without Jensen Huang?",
         "url": "https://wsj.com/a?mod=rss_markets_main", "lean": "보수"},
        {"issue_id": "X", "source": "Wall Street Journal", "kind": "column", "title": "Can Nvidia Thrive Without Jensen Huang?",
         "url": "https://wsj.com/a?mod=rss_opinion", "lean": "보수"},
        {"issue_id": "X", "source": "Bloomberg", "kind": "column", "title": "Can Nvidia Thrive Without Jensen Huang?",
         "url": "https://bloomberg.com/b", "lean": "중도"},
        {"issue_id": "X", "source": "Wall Street Journal", "kind": "column", "title": "Another piece",
         "url": "https://wsj.com/a?mod=rss_opinion2", "lean": "보수"}]}
    got = [(o["source"], o["title"]) for o in related_opinions(op)["X"]]
    assert got == [("Wall Street Journal", "Opinion | Can Nvidia Thrive Without Jensen Huang?"),
                   ("Bloomberg", "Can Nvidia Thrive Without Jensen Huang?"), ("Wall Street Journal", "Another piece")]


def test_organize_dedupes_same_piece():
    from pipeline.opinion import dedupe_opinions

    class A:
        def __init__(self, src, title, kind):
            self.source, self.title, self.opinion = src, title, kind
    xs = [A("WSJ", "Opinion | X", "column"), A("WSJ", "X", "editorial"), A("WSJ", "Y", "column")]
    out = dedupe_opinions(xs)
    assert [(o.title, o.opinion) for o in out] == [("X", "editorial"), ("Opinion | X", "column")][:1] + [("Y", "column")]


# ---------- S51b 가나 → 한글 (⑥) ----------
def test_kana_to_hangul():
    assert kana_to_hangul("라ム슈타인 그룹 회의") == "라무슈타인 그룹 회의"
    assert kana_to_hangul("방공 지원을 둘러싼 라ムシュ타인 회의 결과") == "방공 지원을 둘러싼 라무슈타인 회의 결과"
    assert kana_to_hangul("トランプ大統領、北朝鮮") == "トランプ大統領、北朝鮮"        # 한글 없는 원문은 그대로
    assert kana_to_hangul("東京・大阪 회담") == "東京・大阪 회담"                    # 가운뎃점은 그대로
    assert kana_to_hangul("チャ지ュ キョ ンン") == "차주 쿄 은은"


def test_fix_kana_tree_only_changed_copied():
    ed = {"a": {"b": "라ム슈타인"}, "c": {"d": "그대로"}, "e": ["リビウ 방문", "ニュース"]}
    out = fix_kana_tree(ed)
    assert out["a"]["b"] == "라무슈타인" and out["e"] == ["리비우 방문", "ニュース"]
    assert out["c"] is ed["c"] and ed["a"]["b"] == "라ム슈타인"                      # 원본은 안 바뀜
