"""S55 ④ 외신 꼭지·연재 이름은 원어 그대로 (번역 규칙·캐시 판)."""
import pipeline.llm as L


def test_label_rule_in_prompts_and_cache_versions():
    for p in (L.OP_TITLE_PROMPT, L.KOREAN_PROMPT):
        assert "[Watch]" in p and "원어 그대로" in p and "올리가르히" in p and "빅테이크" in p
        p.format(data="x")
    assert "샤를마뉴" not in L.OP_TITLE_PROMPT and "'Editorial'·'Opinion' 같은 일반 머리말은 뺀다" in L.OP_TITLE_PROMPT
    assert L.OP_TITLE_KEY == "op_title3"
    assert L._korean_key({"issue_id": "i", "title": "t", "llm": {}}).endswith("|k2")   # 한국어 패스도 다시
