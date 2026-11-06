"""S26 1면 첫 쪽 — 메인 기사 1건(사진과 함께) + "자세히 보기"(각도별 묶음).

기준 (project-plan.md S26):
- 메인 기사 (S42): 한국에서도 큰 전세계 이슈에 가점을 주어 한국 최대 이슈와 견준다. 그런 이슈가 없으면 한국 최대 이슈
- 첫 쪽은 메인 기사 하나로 끝난다. 좌우로 나누지 않고, 색인·"○면으로 계속" 없음
- "자세히 보기" → 자세히 창에 요약·배경·쟁점·관점·입장 차이·관련·사설. 같은 기사가 지면에 두 번 실리지 않는다
- 375·390·820·1180 폭에서 넘친 쪽 0, 가로 넘침 없음, 쪽 수 그대로
"""
import copy

import pytest

from pipeline.render import NEWS_SECTIONS, _lead_note, build_context, lead_pick, lead_story, render_html, write_assets
from pipeline.settings import load_config, load_interests, load_sources
from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)

SIZES = [(1180, 820), (820, 1180), (390, 844), (375, 812)]


def _edition(tmp_path):
    """뉴스 면 기사에 AI 분석을 붙인 호. 메인은 어느 뉴스 면에서든 뽑히고, 실제 발행도 지면 전체를 분석한다 (config.yaml analysis_issues)."""
    box = {}

    def keep(out):
        for it in (i for k in NEWS_SECTIONS for i in out["sections"].get(k, [])):
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
    assert lead_story([kr1, kr2, big], C)["title"] == "국내 B"             # 전세계 주목이어도 한국 언론이 안 다루면 한국 이슈 (2026-11-06)
    assert lead_story([_it("국내 C", ["중앙일보"], att=0.95), kr1], C)["title"] == "국내 A"   # 1면에 오른 수 우선
    assert lead_story([weak], C)["title"] == "해외 약함"                 # 한국 기사도 전세계 이슈도 없으면 1면 1위
    assert lead_story([big, weak], C)["title"] == "해외 큰 이슈"           # 한국 기사가 없으면 전세계 이슈


def test_lead_story_global_also_big_in_korea_gets_bonus():
    """전세계 이슈가 한국 신문 1면에도 오르면 가점 3점(1면 한 곳 2점)으로 한국 최대 이슈와 견준다."""
    heads = {"BBC": [1, "feed"], "New York Times": [1, "home"], "Le Monde": [2, "home"]}
    both = _it("세계 이슈", ["BBC", "New York Times", "Le Monde", "NHK World"], {**heads, "조선일보": [2, "naver_a1"]}, countries=4)
    one = _it("국내 1면 한 곳", ["동아일보", "한겨레"], {"동아일보": [1, "naver_a1"]})
    three = _it("국내 1면 세 곳", ["동아일보", "한겨레", "중앙일보"], {n: [1, "naver_a1"] for n in ("동아일보", "한겨레", "중앙일보")})
    assert lead_pick([one, both], C) == (both, "전세계+한국")
    assert lead_pick([three, both], C) == (three, "한국 우세")             # 2+3=5 < 12+1.5


def test_lead_story_paper_top_decides():
    """신문 1면에 실린 것과 맨 위에 실린 것은 다르다 (2026-11-06 시험). 1면 수가 같아도 톱이 있으면 전세계 이슈의 가점을 넘는다."""
    heads = {"BBC": [1, "feed"], "New York Times": [1, "home"], "Le Monde": [2, "home"]}
    world = _it("세계 이슈", ["BBC", "New York Times", "Le Monde", "NHK World"], {**heads, "조선일보": [3, "naver_a1"]}, countries=4)
    inner = _it("국내 1면 안쪽", ["동아일보", "한겨레"], {"동아일보": [2, "naver_a1"], "한겨레": [2, "naver_a1"]})
    top = _it("국내 톱", ["동아일보", "한겨레"], {"동아일보": [1, "naver_a1"], "한겨레": [2, "naver_a1"]})
    assert lead_pick([inner, world], C) == (world, "전세계+한국")          # 2+3=5 >= 4+1
    assert lead_pick([top, world], C) == (top, "한국 우세")                # 2+3=5 < 4+2+1
    tops = {n: [1, "naver_a1"] for n in ("조선일보", "중앙일보", "동아일보")}
    win = _it("세계 이슈, 신문 톱도", ["BBC", "New York Times", "Le Monde", "NHK World"], {**heads, **tops}, countries=5)
    assert lead_pick([top, win], C) == (win, "전세계+한국")                # 세계적으로 크고 신문 톱이면 그대로 메인


def test_lead_story_korean_coverage_alone_counts_as_big():
    """1면에 안 올라도 한국 매체 4곳이 다루면 한국에서도 큰 이슈. 한국 기사 비중이 높아도 전세계 이슈에서 빠지지 않는다."""
    wide = _it("세계·국내 함께", ["조선일보", "중앙일보", "동아일보", "한겨레", "BBC"], countries=6)
    small = _it("국내 작음", ["중앙일보"])
    assert lead_pick([small, wide], C) == (wide, "전세계+한국")
    assert lead_pick([small, _it("세계만", ["BBC", "Le Monde", "Al Jazeera"], countries=6)], C)[1] == "한국 이슈"


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


def test_lead_note_records_why_and_paper_top():
    """판정 기록: 고른 까닭·점수와 신문 톱 최다 기사. 신문 1면 자료가 없는 날은 비워 둔다."""
    a = _it("국내 톱", ["동아일보", "한겨레"], {"동아일보": [1, "naver_a1"], "한겨레": [1, "naver_a1"]})
    b = _it("국내 안쪽", ["중앙일보"], {"중앙일보": [2, "naver_a1"]})
    for r in (a, b):
        r["view"] = {"title": r["title"]}
    note = _lead_note(a, "한국 이슈", [b, a], C)
    assert note["why"] == "한국 이슈" and note["signals"]["korea"] == 9 and note["a1_leader"] == {"title": "국내 톱", "tops": 2}
    plain = _it("1면 자료 없음", ["중앙일보"])
    assert _lead_note(plain, "한국 이슈", [plain], C)["a1_leader"] is None


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
