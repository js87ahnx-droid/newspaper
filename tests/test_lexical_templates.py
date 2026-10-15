from pipeline.lexical import drop_source_templates, tokens


def test_source_template_tokens_dropped():
    titles = [
        ("WSJ", "Auto & Transport Roundup: Market Talk"),
        ("WSJ", "Energy & Utilities Roundup: Market Talk"),
        ("WSJ", "Financial Services Roundup: Market Talk"),
        ("BBC", "Netflix to cut jobs"),
    ]
    docs = drop_source_templates([tokens(t) for _, t in titles], [s for s, _ in titles])
    assert "roundup" not in docs[0] and "market" not in docs[0]
    assert "auto" in docs[0]
    assert "netflix" in docs[3]


def test_shared_event_tokens_kept_across_sources():
    titles = [
        ("연합", "김지용 중수청장 임명"),
        ("연합", "김지용 임명 속보"),
        ("연합", "김지용 앞 과제"),
        ("조선", "김지용 중수청장 임명안 재가"),
    ]
    docs = drop_source_templates([tokens(t) for _, t in titles], [s for s, _ in titles])
    # 김지용은 다른 매체에도 나오므로(4건 중 연합 3건 = 75% < 80%) 지우지 않는다
    assert "김지" in docs[0]
