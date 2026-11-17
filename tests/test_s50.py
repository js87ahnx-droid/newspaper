"""S50 큐레이션 판: 설정·변환·두 판 발행."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from pipeline.settings import Curated, load_config


# ---------- S50a 설정 ----------
def test_curated_config_loads():
    c = load_config().curated
    assert c.enabled and c.keep["politics"] == 4 and c.list_max == 6
    cfg = load_config()
    assert sum(c.pages.get(s.id, s.pages) for s in cfg.sections) <= 24


@pytest.mark.parametrize("bad", [
    {"keep": {"front": 3}},          # 1면은 줄이지 않음
    {"keep": {"jonghap": 5}},        # 종합면은 큐레이션 판에서 창으로 접힘 (S51)
    {"keep": {"briefs": 3}},
    {"keep": {"politics": 0}},       # 면 머리는 늘 남김
    {"pages": {"politics": -1}},
    {"list_max": 30},
    {"keep": {"nowhere": 3}},
])
def test_curated_config_rejects(bad):
    with pytest.raises(ValidationError):
        Curated(**bad)


# ---------- S50b 큐레이션 변환 ----------
import copy  # noqa: E402

from pipeline.edit import arrange, choose, edition_to_json  # noqa: E402
from pipeline.interest import build_interest_table  # noqa: E402
from pipeline.render import CURATE_SECTIONS, build_context, curate, render_html  # noqa: E402
from pipeline.score import score_issues  # noqa: E402
from pipeline.settings import load_interests, load_sources  # noqa: E402
from pipeline.stance import day_prior, stance  # noqa: E402
from tests.test_edit import build  # noqa: E402

KEEP = {"politics": 4, "economy": 4, "international": 5, "society": 3, "interest": 5}   # 종합면은 S51 에서 창으로 접힘


def _edition(mutate=None, n=90):
    cfg, interests = load_config(), load_interests()
    arts, issues = build(n)
    scored = score_issues(issues, arts, cfg, build_interest_table(interests), [])
    placed, st = choose(scored, cfg, interests)
    out = edition_to_json(arrange(placed, cfg, interests, arts), "2026-10-16", arts, st)
    prior = day_prior(list(arts.values()))
    for it in [i for ps in out["sections"].values() for i in ps] + out["compare"]:
        it["stance"] = stance([arts[a["id"]] for a in it["articles"]], prior)
    if mutate:
        mutate(out)
    return out


def _ctx(ed, variant=None):
    return build_context(copy.deepcopy(ed), load_config(), load_interests(), load_sources(), variant=variant)


def _news_ids(sections, sid):
    s = next((x for x in sections if x["id"] == sid), None)
    return [r["issue_id"] for r in s["items"] if not r.get("reserve")] if s else []


def test_curate_counts_and_nothing_lost():
    ed = _edition()
    base, cur = _ctx(ed)["sections"], _ctx(ed, "b")["sections"]
    src = next(s for s in cur if s["id"] == "curated_src")
    src_ids = [r["issue_id"] for r in src["items"]]
    assert len(src_ids) == len(set(src_ids))
    added_briefs = set(_news_ids(cur, "briefs")) - set(_news_ids(base, "briefs"))
    trimmed = 0
    for sid in ("politics", "economy", "international", "society", "interest"):
        b, c = _news_ids(base, sid), _news_ids(cur, sid)
        if not b:
            continue
        assert len(c) <= KEEP[sid] and c[0] == b[0]                      # 면 머리는 늘 남음
        sec = next(x for x in cur if x["id"] == sid)
        listed = [m["issue_id"] for m in sec.get("more", [])]
        assert len(listed) <= 6 and set(listed) <= set(src_ids)
        rest = set(b) - set(c)
        assert rest == set(listed) | (rest & added_briefs)               # 남김 ∪ 목록 ∪ 단신 = 원래
        assert not (set(c) & set(listed))
        assert not (set(listed) & added_briefs)                           # 목록과 단신 추가분도 겹치지 않음 (구현 리뷰 N4)
        assert c == [i for i in b if i in c]                              # 남긴 것은 원래 순서
        trimmed += len(rest)
    assert trimmed > 0
    heads = [r for s in cur if s["id"] in CURATE_SECTIONS for r in s["items"] if r.get("sec_head")]
    assert len(heads) == sum(1 for s in cur if s["id"] in CURATE_SECTIONS and _news_ids(cur, s["id"]))
    # 1면·종합면 고르기는 두 판이 같다
    assert _news_ids(base, "front") == _news_ids(cur, "front")
    assert next(s for s in base if s["id"] == "front").get("lead", {}).get("issue_id") == \
        next(s for s in cur if s["id"] == "front").get("lead", {}).get("issue_id")


class _C:
    keep = {"politics": 3}
    list_max = 1


def _r(i, paper=False, guaranteed=False, reserve=False):
    return {"issue_id": i, "view": {"title": "t" + i}, "source": "S", "topic": "politics", "url": "u" + i,
            "headline_by": {"조선": [2, "naver_a1"]} if paper else {"BBC": [1, "feed"]}, "pages_by": {},
            "guaranteed": guaranteed, "reserve": reserve}


def test_curate_prefers_paper_signal_and_overflow_to_briefs():
    """국내 면(정치): 머리 + 신문 지면 신호 먼저, 그다음 점수 순. 보장 기사(다양성 등)는 앞세우지 않는다 (S51 ⑦)."""
    secs = [{"id": "politics", "items": [_r("h"), _r("a"), _r("b", paper=True), _r("c"), _r("d", guaranteed=True), _r("z", reserve=True)]},
            {"id": "briefs", "items": [_r("x")]}]
    curate(secs, _C)
    pol = secs[0]
    assert [r["issue_id"] for r in pol["items"]] == ["h", "a", "b", "z"]   # 머리 + 신호(b)·다음(a), 원래 순서, 예비 그대로
    assert [m["issue_id"] for m in pol["more"]] == ["c"]                    # 목록 상한 1 — 남김 다음 순서
    assert [r["issue_id"] for r in secs[1]["items"]] == ["x", "d"]          # 넘친 것은 단신 후보
    assert [r["issue_id"] for r in secs[2]["items"]] == ["c"] and secs[2]["id"] == "curated_src"
    assert pol["items"][0]["sec_head"] and not pol["items"][1].get("sec_head")


def test_curate_pages_by_counts_as_paper():
    r = _r("p")
    r["pages_by"] = {"동아": "A3"}
    secs = [{"id": "politics", "items": [_r("h"), _r("a"), _r("b"), r]}, {"id": "briefs", "items": []}]
    curate(secs, _C)
    assert [x["issue_id"] for x in secs[0]["items"]] == ["h", "a", "p"]   # A3면 신호가 점수 순보다 먼저


def test_curate_off_or_no_variant_changes_nothing():
    ed = _edition()
    cfg = load_config()
    a = render_html(copy.deepcopy(ed), cfg, load_interests(), load_sources())
    off = cfg.model_copy(update={"curated": cfg.curated.model_copy(update={"enabled": False})})
    b = render_html(copy.deepcopy(ed), off, load_interests(), load_sources(), variant="b")
    assert a == b and "ed-curated" not in a and "more-list" not in a and "tb-var" not in a


def test_render_b_client_config_and_review():
    ed = _edition()
    cfg = load_config()
    html = render_html(copy.deepcopy(ed), cfg, load_interests(), load_sources(), base="", variant="b")
    import json
    import re
    client = json.loads(re.search(r'window.EDITION = (.*?);</script>', html, re.S).group(1))
    assert client["curated"] is True and client["sectionPages"]["politics"] == 2 and client["sectionCaps"]["interest"] == 5
    base_client = json.loads(re.search(r'window.EDITION = (.*?);</script>', render_html(copy.deepcopy(ed), cfg, load_interests(), load_sources()), re.S).group(1))
    assert client["review"] == base_client["review"]                       # 리뷰 목록은 기존 판 순서 (S53 결정 5)
    assert 'class="ed-curated"' in html and 'class="more-list"' in html and 'class="curated-src" hidden' in html
    assert 'href="./" aria-label="오늘 호" aria-current="page"' in html     # S53: 오늘 = 루트
    assert "tb-var" not in html


# ---------- S50e 두 판 발행 ----------
def test_publish_curated_only(tmp_path):
    """S53: 큐레이션 판 하나만, 기존 주소로. b/ 는 지우되 지난 날짜 보관본의 b/ 는 남긴다."""
    from pipeline.publish import publish
    ed = _edition()
    cfg = load_config()
    site = tmp_path / "docs"
    (site / "b").mkdir(parents=True)
    (site / "b" / "index.html").write_text("old", encoding="utf-8")
    (site / "archive/2026-10-16/b").mkdir(parents=True)
    (site / "archive/2026-10-16/b/index.html").write_text("old", encoding="utf-8")
    (site / "archive/2026-10-15/b").mkdir(parents=True)
    (site / "archive/2026-10-15/b/index.html").write_text("old", encoding="utf-8")
    files = publish(copy.deepcopy(ed), cfg, load_interests(), load_sources(), site)
    rel = [f.relative_to(site).as_posix() for f in files]
    assert rel == ["index.html", "archive/2026-10-16/index.html", "archive/index.html", "b/index.html", "archive/2026-10-16/b/index.html"]
    import json
    import re
    from pipeline.publish import REDIRECT
    from pipeline.render import build_context, review_list
    for f, base in (("index.html", ""), ("archive/2026-10-16/index.html", "../../")):
        c = json.loads(re.search(r'window.EDITION = (.*?);</script>', (site / f).read_text(encoding="utf-8"), re.S).group(1))
        assert c["curated"] is True and c["base"] == base and c["sectionPages"]["jonghap"] == 0
        assert c["sectionPages"] == {**c["sectionPages"], **cfg.curated.pages} and c["sectionCaps"]["politics"] == cfg.curated.keep["politics"]
        assert c["review"] == review_list(build_context(copy.deepcopy(ed), cfg, load_interests(), load_sources())["sections"])   # 결정 5
    a, aa = (site / "index.html").read_text(encoding="utf-8"), (site / "archive/2026-10-16/index.html").read_text(encoding="utf-8")
    assert "ed-curated" in a and "ed-curated" in aa and "tb-var" not in a and "tb-var" not in aa
    assert 'href="static/app.css' in a and 'href="../../static/app.css' in aa
    assert 'href="./" aria-label="오늘 호" aria-current="page"' in a
    assert 'href="../../" aria-label="오늘 호"' in aa and 'aria-current' not in aa.split('aria-label="오늘 호"')[1][:30]
    assert (site / "b/index.html").read_text(encoding="utf-8") == REDIRECT == (site / "archive/2026-10-16/b/index.html").read_text(encoding="utf-8")
    assert 'url=../"' in REDIRECT and "location.replace" in REDIRECT                  # 옛 b/ 주소 → 지면 (계획 리뷰 M1)
    assert (site / "archive/2026-10-15/b/index.html").exists()             # 지난 날짜 b 는 남김
    # 끄면 기존 판 하나
    off = cfg.model_copy(update={"curated": cfg.curated.model_copy(update={"enabled": False})})
    files = publish(copy.deepcopy(ed), off, load_interests(), load_sources(), site)
    assert len(files) == 5 and "ed-curated" not in (site / "index.html").read_text(encoding="utf-8")
    fresh = tmp_path / "fresh"                                                           # b/ 가 없던 곳엔 만들지 않는다
    assert len(publish(copy.deepcopy(ed), cfg, load_interests(), load_sources(), fresh)) == 3 and not (fresh / "b").exists()
