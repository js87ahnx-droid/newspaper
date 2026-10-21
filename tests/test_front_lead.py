"""S26 1면 첫 쪽 — 메인 기사 1건(사진과 함께) + "자세히 보기"(각도별 묶음).

기준 (project-plan.md S26):
- 메인 기사: 전세계가 주목하는 해외 이슈가 있으면 그것, 없으면 한국 신문 1면에 가장 많이 오른 한국 기사
- 첫 쪽은 메인 기사 하나로 끝난다. 좌우로 나누지 않고, 색인·"○면으로 계속" 없음
- "자세히 보기" → 자세히 창에 요약·배경·쟁점·관점·입장 차이·관련·사설. 같은 기사가 지면에 두 번 실리지 않는다
- 375·390·820·1180 폭에서 넘친 쪽 0, 가로 넘침 없음, 쪽 수 그대로
"""
import copy

import pytest

from pipeline.render import build_context, lead_story, render_html, write_assets
from pipeline.settings import load_config, load_interests, load_sources
from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)

SIZES = [(1180, 820), (820, 1180), (390, 844), (375, 812)]


def _edition(tmp_path):
    """1면 기사에 AI 분석을 붙인 호."""
    box = {}

    def keep(out):
        for it in out["sections"]["front"]:
            it.setdefault("llm", {})["analysis"] = {
                "headline": it["title"], "summary": "요약 문장입니다. " * 6, "brief": "한 줄 부제입니다",
                "background": "배경 설명 " * 15, "points": ["쟁점 하나 " * 4, "쟁점 둘 " * 4], "stances": []}
        box["ed"] = copy.deepcopy(out)
    make_site(tmp_path / "seed", mutate=keep)
    return box["ed"]


def _it(title, srcs, heads=None, countries=1, att=0.5, front=False):
    return {"title": title, "articles": [{"source": s} for s in srcs], "headline_by": heads or {},
            "coverage": {"countries": countries}, "scores": {"attention": att}, "_front": front}


C = {"조선일보": "KR", "중앙일보": "KR", "동아일보": "KR", "한겨레": "KR", "BBC": "GB", "New York Times": "US", "Le Monde": "FR",
     "NHK World": "JP", "Al Jazeera": "QA"}


def test_lead_story_korea_first_unless_global():
    kr1 = _it("국내 A", ["조선일보", "중앙일보"], {"조선일보": [1, "naver_a1"]}, att=0.9, front=True)
    kr2 = _it("국내 B", ["동아일보", "한겨레", "BBC"], {"동아일보": [1, "naver_a1"], "한겨레": [1, "naver_a1"]}, att=0.6)
    weak = _it("해외 약함", ["BBC", "Le Monde", "NHK World"], {"BBC": [1, "feed"]}, countries=5, att=1.0, front=True)
    assert lead_story([weak, kr1, kr2], C)["title"] == "국내 B"            # 한국 신문 1면 2곳 > 1곳, 해외 5개국은 전세계 주목 아님
    big = _it("해외 큰 이슈", ["BBC", "New York Times", "Le Monde", "NHK World"],
              {"BBC": [1, "feed"], "New York Times": [1, "home"], "Le Monde": [2, "home"]}, countries=4, att=0.7)
    assert lead_story([kr1, kr2, big], C)["title"] == "해외 큰 이슈"
    assert lead_story([kr1, _it("6개국 보도", ["BBC", "Le Monde", "Al Jazeera"], countries=6)], C)["title"] == "6개국 보도"
    assert lead_story([_it("국내 C", ["중앙일보"], att=0.95), kr1], C)["title"] == "국내 A"   # 1면에 오른 수 우선
    assert lead_story([weak], C)["title"] == "해외 약함"                 # 한국 기사도 전세계 이슈도 없으면 1면 1위


def test_front_lead_and_detail_source(tmp_path):
    ed = _edition(tmp_path)
    cfg, interests, sources = load_config(), load_interests(), load_sources()
    secs = build_context(ed, cfg, interests, sources)["sections"]
    lead = secs[0]["lead"]
    assert all(r["issue_id"] != lead["issue_id"] for s in secs if s["id"] != "detail" for r in s["items"])   # 지면에 한 번만
    assert secs[-1]["id"] == "detail" and secs[-1]["items"][0]["issue_id"] == lead["issue_id"]
    html = render_html(ed, cfg, interests, sources)
    flow = html[html.index('<div id="flow"'):]
    z0 = flow.index('class="item fz"')
    zone = flow[z0:flow.index('<article class="item', z0)]
    assert zone.count('class="fz-art') == 1 and "data-more" in zone and "an-bg" not in zone
    d0 = flow.index('<div class="detail-src" hidden>')
    detail = flow[d0:flow.index("</article>", d0)]
    assert "<span>1</span>요약" in detail and "<span>2</span>왜 생겼나 <small>배경</small>" in detail
    assert "<span>3</span>무엇이 쟁점인가" in detail and detail.count('class="lead') == 1 and 'class="photo"' not in detail
    assert "variant" not in html and "tb-variant" not in html and 'class="jump"' not in html   # 비교 판 정리됨


def test_lead_photo_fallback(tmp_path):
    ed = _edition(tmp_path)
    for it in (i for ps in ed["sections"].values() for i in ps):
        it["photo"] = None
        it["photo_alt"], it["photo_alt_source"] = "https://img.test/alt.jpg", "BBC"
    lead = build_context(ed, load_config(), load_interests(), load_sources())["sections"][0]["lead"]
    assert lead["photo"] == "https://img.test/alt.jpg" and lead["photo_source"] == "BBC"


@pytest.mark.parametrize("w,h", SIZES)
def test_front_lead_in_browser(browser, tmp_path, w, h):  # noqa: F811
    ed = _edition(tmp_path)
    cfg = load_config()
    site = tmp_path / "site"
    write_assets(site, "t")
    index = site / "index.html"
    index.write_text(render_html(ed, cfg, load_interests(), load_sources()), encoding="utf-8")
    ctx, page, errors = open_page(browser, index, w, h)
    m = page.evaluate("""() => {
      const p0 = document.querySelector('#book .page[data-page="0"]');
      return { st: NEWS.state(), arts: p0.querySelectorAll('.fz-art').length, items: p0.querySelectorAll('article.item').length,
               photo: !!p0.querySelector('.fz-lead .photo img'), clip: !!p0.querySelector('.item.fz.clip'),
               detailOnPage: document.querySelectorAll('#book .pkg').length,
               sw: document.scrollingElement.scrollWidth, iw: innerWidth };
    }""")
    page.evaluate("document.querySelector(\"#book .page[data-page='0'] .detail-btn\").click()")   # 주간 설문 창이 덮을 수 있어 직접
    page.wait_for_timeout(300)
    rd = page.evaluate("({open: !document.getElementById('reader').hidden, parts: document.querySelectorAll('#reader .pkg-part').length})")
    ctx.close()
    assert not errors, errors
    assert m["st"]["overflow"] == [] and m["sw"] <= m["iw"] and not m["clip"]
    assert m["arts"] == 1 and m["items"] == 0 and m["detailOnPage"] == 0
    assert m["st"]["pages"] == sum(s.pages for s in cfg.sections)
    assert rd["open"] and rd["parts"] >= 3
