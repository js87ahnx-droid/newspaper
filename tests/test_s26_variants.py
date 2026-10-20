"""S26 비교 판 — 기존·A안·B안 세 판 발행, 1면 3구역, 1면 → 이어받는 칸.

기준 (project-plan.md S26):
- publish 가 판마다 HTML 을 쓰고(암호화 목록에 포함), 판 고르기 링크가 맞는 주소로 간다. 비교 판이 없으면 지금과 같다
- 1면 3구역: 글 톱·사진 톱·아래 띠. 분석은 1면에 없고 이어받는 칸에
- A안: 이어받는 칸이 분야 면 맨 위 / B안: 1면 바로 뒤 이슈 면
- 375·390·820·1180 폭에서 넘친 쪽 0, 가로 넘침 없음, "계속" 쪽 번호 = 이어받는 칸이 있는 쪽, 누르면 그 쪽으로
"""
import copy
import json
from pathlib import Path

import pytest

from pipeline.publish import publish, variant_links
from pipeline.render import build_context, josa_ro, render_html, write_assets
from pipeline.settings import load_config, load_interests, load_sources
from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)

SIZES = [(1180, 820), (820, 1180), (390, 844), (375, 812)]


def _analysis(out):
    """1면 기사에 AI 분석을 붙인다 (이어받는 칸에 실릴 내용)."""
    for it in out["sections"]["front"]:
        it.setdefault("llm", {})["analysis"] = {
            "headline": it["title"], "summary": "요약 문장입니다. " * 6, "brief": "한 줄 부제입니다",
            "background": "배경 설명 " * 15, "points": ["쟁점 하나 " * 4, "쟁점 둘 " * 4], "stances": []}


def _edition(tmp_path):
    box = {}

    def keep(out):
        _analysis(out)
        box["ed"] = copy.deepcopy(out)
    make_site(tmp_path / "seed", mutate=keep)
    return box["ed"]


def _cfg(variants):
    cfg = load_config()
    return cfg.model_copy(update={"layout_variants": variants})


def test_josa():
    assert [josa_ro(w) for w in ("정치·안보", "경제·산업", "국제", "사회·과학", "이슈 면", "관심")] == ["로", "으로", "로", "으로", "으로", "으로"]


def test_variant_links_paths():
    assert variant_links([], "base", "") == []
    today = variant_links(["a", "b"], "base", "archive/2026-10-21/")
    assert [(l["label"], l["href"], l["on"]) for l in today] == [
        ("기존", "archive/2026-10-21/", True), ("A안", "archive/2026-10-21/a/", False), ("B안", "archive/2026-10-21/b/", False)]
    inside_a = variant_links(["a", "b"], "a", "../")
    assert [(l["href"], l["on"]) for l in inside_a] == [("../", False), ("../a/", True), ("../b/", False)]
    arch = variant_links(["a", "b"], "base", "")
    assert arch[0]["href"] == "./" and arch[1]["href"] == "a/"


def test_publish_writes_variants_and_base_unchanged(tmp_path):
    ed = _edition(tmp_path)
    interests, sources = load_interests(), load_sources()
    files = publish(ed, _cfg(["a", "b"]), interests, sources, tmp_path / "site")
    rel = sorted(p.relative_to(tmp_path / "site").as_posix() for p in files)
    d = ed["edition"]
    assert rel == sorted(["index.html", f"archive/{d}/index.html", "archive/index.html",
                          f"archive/{d}/a/index.html", f"archive/{d}/b/index.html"])
    a_html = (tmp_path / "site" / "archive" / d / "a" / "index.html").read_text(encoding="utf-8")
    assert 'href="../../../static/app.css' in a_html and 'class="tb-variant"' in a_html
    # 비교 판이 없으면: 3개, 판 고르기 없음, 기존 판 본문은 비교 판이 있을 때와 같다
    files0 = publish(ed, _cfg([]), interests, sources, tmp_path / "site0")
    assert len(files0) == 3
    base0 = (tmp_path / "site0" / "index.html").read_text(encoding="utf-8")
    base1 = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "tb-variant" not in base0 and 'class="item fz"' not in base0
    strip = lambda h: h[h.index('<div id="flow"'):]
    assert strip(base0) == strip(base1)


@pytest.mark.parametrize("variant", ["a", "b"])
def test_front_zone_and_continuation(tmp_path, variant):
    ed = _edition(tmp_path)
    cfg = _cfg([variant])
    ctx = build_context(ed, cfg, load_interests(), load_sources(), variant)
    secs = ctx["sections"]
    front = secs[0]
    zone = front["zone"]
    assert set(zone) == {"top", "photo", "bottom"}
    ids = [zone[k]["issue_id"] for k in ("top", "photo", "bottom")]
    assert len(set(ids)) == 3 and ids[0] == ed["sections"]["front"][0]["issue_id"]
    assert all(r["issue_id"] not in ids for r in front["items"])          # 3구역 기사는 1면 목록에 다시 없음
    if any(r.get("photo") for r in ed["sections"]["front"][1:5]):
        assert zone["photo"].get("photo")
    conts = {r["issue_id"]: s["id"] for s in secs for r in s["items"] if r.get("cont")}
    assert set(conts) == set(ids)                                          # 셋 다 이어받는 칸이 하나씩
    if variant == "b":
        assert secs[1]["id"] == "issue" and [r["issue_id"] for r in secs[1]["items"]] == ids
    else:
        for s in secs:
            mine = [r for r in s["items"] if r.get("cont")]
            if mine:
                assert s["items"][:len(mine)] == mine                      # 분야 면 맨 위
        assert "issue" not in [s["id"] for s in secs]
    html = render_html(ed, cfg, load_interests(), load_sources(), variant=variant)
    flow = html[html.index('<div id="flow"'):]
    z0 = flow.index('class="item fz"')
    zone_html = flow[z0:flow.index('<article class="item', z0)]           # 3구역 덩어리만 (1면 4·5번째 기사는 그대로)
    assert "an-bg" not in zone_html and "cmp-inline" not in zone_html     # 분석은 1면에 없음
    assert flow.count('class="cont-band"') == 3


@pytest.mark.parametrize("variant", ["a", "b"])
@pytest.mark.parametrize("w,h", SIZES)
def test_variant_layout_in_browser(browser, tmp_path, variant, w, h):  # noqa: F811
    ed = _edition(tmp_path)
    cfg = _cfg([variant])
    site = tmp_path / "site"
    write_assets(site, "t")
    (site / variant).mkdir()
    index = site / variant / "index.html"
    index.write_text(render_html(ed, cfg, load_interests(), load_sources(), base="../", variant=variant), encoding="utf-8")
    ctx, page, errors = open_page(browser, index, w, h)
    m = page.evaluate("""() => {
      const st = NEWS.state();
      const pg = i => document.querySelector('#book .page[data-page="' + i + '"]');
      const jumps = [...document.querySelectorAll('#book .jump')].map(b => ({
        hidden: b.hidden, page: +b.getAttribute('data-page'),
        ok: !!(pg(b.getAttribute('data-page')) || document).querySelector('article.cont[data-issue="' + b.dataset.jump + '"]') }));
      const ix = [...document.querySelectorAll('#book .fz-index .ix')].map(b => {
        const i = +b.dataset.goto, p = pg(i), prev = pg(i - 1);
        const sec = (/sec-([\\w-]+)/.exec(p.className) || [])[1];
        return { sec, first: !prev || !prev.classList.contains('sec-' + sec) };
      });
      return { st, jumps, ix, zoneOnFirst: !!pg(0).querySelector('.item.fz'), clip: !!document.querySelector('#book .item.fz.clip'),
               sw: document.scrollingElement.scrollWidth, iw: innerWidth,
               issueFirst: (pg(2) || pg(1)).className };
    }""")
    first = m["jumps"][0]
    page.evaluate("document.querySelector(\"#book .page[data-page='0'] .fz-top .jump\").click()")   # 주간 설문 창이 덮을 수 있어 직접
    page.wait_for_timeout(1200)
    cur = page.evaluate("NEWS.state()")
    ctx.close()
    assert not errors, errors
    assert m["st"]["overflow"] == [] and m["sw"] <= m["iw"]
    assert m["zoneOnFirst"] and not m["clip"]
    assert len(m["jumps"]) == 3 and all(not j["hidden"] and j["ok"] for j in m["jumps"])
    if w >= 700:   # 색인은 넓은 쪽만 (휴대폰은 숨김)
        assert m["ix"] and all(x["first"] for x in m["ix"])
    expected = sum(s.pages for s in cfg.sections) + (2 if variant == "b" else 0)
    assert m["st"]["pages"] == expected
    step = 2 if cur["spread"] and cur["mode"] == "flip" else 1
    assert cur["current"] <= first["page"] < cur["current"] + step     # "계속"을 누르면 그 쪽이 보인다
    if variant == "b":
        assert "sec-issue" in m["issueFirst"]
