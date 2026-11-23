"""S59: 논평면 묶음 제목·"관련:" 줄은 지면에 보이는 한국어 제목으로."""
from pipeline.render import _opinion_view, shown_titles
from pipeline.settings import load_interests


def _item(iid, title, headline=None, merged=()):
    it = {"issue_id": iid, "title": title, "lead": "", "merged": list(merged),
          "articles": [{"title": title, "lang": "zh", "source": "x", "url": "u"}]}
    if headline:
        it["llm"] = {"analysis": {"headline": headline, "summary": "s"}}
    return it


def test_opinion_titles_use_shown_korean_title():
    zh = "韩国教育部长官因应对高考作弊引发混乱提出辞职"
    ed = {"sections": {"politics": [_item("i1", zh, "교육부 장관, 수능 혼란 책임지고 사퇴", merged=["i9"])],
                       "world": [_item("i2", "Other", None)]}}
    shown = shown_titles(ed, load_interests().foreign_display)
    assert shown["i1"] == shown["i9"] == "교육부 장관, 수능 혼란 책임지고 사퇴"
    e = {"issue_id": "i9", "issue_title": zh, "lean": "보수"}
    op = {"compare": [{"issue_id": "i1", "issue_title": zh, "on_page": True, "groups": [{"lean": "보수", "editorials": [e]}]},
                      {"issue_id": None, "issue_title": "주제 이름", "on_page": False, "groups": []}],
          "editorials": [dict(e)], "columns": [{"issue_id": "i1", "issue_title": zh, "lean": "진보"}, {"issue_id": None, "lean": "진보"}]}
    v = _opinion_view(op, shown)
    assert v["compare"][0]["issue_title"] == "교육부 장관, 수능 혼란 책임지고 사퇴"
    assert v["compare"][1]["issue_title"] == "주제 이름"                    # 지면에 없는 묶음은 그대로
    assert v["compare"][0]["groups"][0]["editorials"][0]["issue_title"] == shown["i1"]
    assert v["editorial_chunks"][0][0]["issue_title"] == shown["i1"] and v["columns"][0]["issue_title"] == shown["i1"]
    assert "issue_title" not in v["columns"][1]
    assert _opinion_view(op, shown)["compare"][0]["issue_title"] == shown["i1"]   # 같은 호 두 판(두 번 그림)도 같음
    assert op["compare"][0]["issue_title"] == zh                           # 묶음 원본은 그대로
