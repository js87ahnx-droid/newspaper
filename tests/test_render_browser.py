"""S8 지면 — 실제 브라우저(Playwright Chromium)로 측정.

기준 (project-plan.md S8):
- 아이패드 가로 해상도 4종에서 가로 스크롤 없음 (+ 모든 쪽의 내용이 쪽 안에 들어감)
- 끌기로 쪽이 넘어간다 / 동작 줄이기면 애니메이션 없는 넘김
- 제호가 호 날짜로 자동 표기
- 기사 표시 요소 8종 / 본문 없음(리드 상한) / 깨진 사진은 자리를 접음
"""
import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

from pipeline.edit import arrange, choose, edition_to_json
from pipeline.interest import build_interest_table
from pipeline.render import render
from pipeline.score import issue_signature, score_issues, title_df
from pipeline.settings import load_config, load_interests, load_sources
from pipeline.stance import day_prior, stance
from pipeline.textutil import LEAD_MAX
from tests.test_edit import build

pw = pytest.importorskip("playwright.sync_api")

IPADS = [(1024, 768), (1180, 820), (1194, 834), (1366, 1024)]


def make_site(tmp_path: Path, edition_date="2026-10-16", broken_photo=False, previous=None) -> Path:
    cfg, interests, sources = load_config(), load_interests(), load_sources()
    arts, issues = build()
    for a in arts.values():  # 리드는 RSS 상한까지 긴 것으로 (쪽 넘침을 잘 드러내도록)
        a.lead = ("긴 리드 문장입니다. " * 40)[:LEAD_MAX]
        if broken_photo and a.image:
            a.image = "http://127.0.0.1:9/broken.jpg"
    scored = score_issues(issues, arts, cfg, build_interest_table(interests), previous or [])
    placed, st = choose(scored, cfg, interests)
    ed = arrange(placed, cfg, interests, arts)
    out = edition_to_json(ed, edition_date, arts, st)
    prior = day_prior(list(arts.values()))
    for it in [i for ps in out["sections"].values() for i in ps] + out["compare"]:
        it["stance"] = stance([arts[a["id"]] for a in it["articles"]], prior)
    site = tmp_path / "site"
    render(out, cfg, interests, sources, site)
    return site / "index.html"


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # 브라우저 미설치
            pytest.skip(f"chromium 없음: {e}")
        yield b
        b.close()


def open_page(browser, index: Path, w, h, reduced=False):
    ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=True,
                              reduced_motion="reduce" if reduced else "no-preference")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(index.as_uri())
    page.wait_for_function("window.NEWS && window.NEWS.state().pages > 0")
    return ctx, page, errors


@pytest.mark.parametrize("w,h", IPADS)
def test_no_horizontal_scroll_and_pages_fit(browser, tmp_path, w, h):
    index = make_site(tmp_path)
    ctx, page, errors = open_page(browser, index, w, h)
    m = page.evaluate("""() => ({
        sw: document.scrollingElement.scrollWidth, iw: innerWidth,
        book: document.getElementById('book').getBoundingClientRect().width,
        spread: NEWS.state().spread,
        overflow: [...document.querySelectorAll('#book .page-inner')].filter(e => e.scrollHeight > e.clientHeight + 1).length,
        pages: NEWS.state().pages })""")
    ctx.close()
    assert not errors, errors
    assert m["sw"] <= m["iw"] and m["book"] <= m["iw"]
    assert m["spread"] is True            # 가로 화면 = 두 쪽 펼침
    assert m["overflow"] == 0, f"내용이 넘친 쪽 {m['overflow']}개"
    assert m["pages"] >= 4


def test_drag_flips_page(browser, tmp_path):
    index = make_site(tmp_path)
    ctx, page, _ = open_page(browser, index, 1180, 820)
    assert page.evaluate("NEWS.state().flip") is True
    box = page.locator("#book").bounding_box()
    x0, y0 = box["x"] + box["width"] - 5, box["y"] + box["height"] - 5   # 오른쪽 아래 모서리
    page.mouse.move(x0, y0)
    page.mouse.down()
    for i in range(1, 21):                                                # 손가락을 따라 끌기
        page.mouse.move(x0 - i * box["width"] * 0.04, y0 - i * 6)
    page.mouse.up()
    page.wait_for_timeout(1200)
    cur = page.evaluate("NEWS.state().current")
    ctx.close()
    assert cur == 2


def test_reduced_motion_simple_flip(browser, tmp_path):
    index = make_site(tmp_path)
    ctx, page, _ = open_page(browser, index, 1180, 820, reduced=True)
    assert page.evaluate("NEWS.state().flip") is False
    page.click('[data-act="next"]')
    cur = page.evaluate("NEWS.state().current")
    visible = page.evaluate("[...document.querySelectorAll('#book .page')].filter(p => p.style.display !== 'none').length")
    ctx.close()
    assert cur == 2 and visible == 2


def test_portrait_single_page(browser, tmp_path):
    index = make_site(tmp_path)
    ctx, page, _ = open_page(browser, index, 820, 1180)
    st = page.evaluate("NEWS.state()")
    sw = page.evaluate("document.scrollingElement.scrollWidth <= innerWidth")
    ctx.close()
    assert st["spread"] is False and sw


def test_masthead_follows_edition_date(browser, tmp_path):
    for d, expect in (("2026-10-16", "10월 16일자 뉴스"), ("2027-01-03", "1월 3일자 뉴스")):
        index = make_site(tmp_path / d, edition_date=d)
        ctx, page, _ = open_page(browser, index, 1180, 820)
        title = page.title()
        mast = page.locator("#book .masthead").first.inner_text()
        app = page.get_attribute('meta[name="apple-mobile-web-app-title"]', "content")
        ctx.close()
        manifest = json.loads((index.parent / "manifest.webmanifest").read_text(encoding="utf-8"))
        assert title == mast == app == manifest["name"] == expect


class ItemParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items, self.cur, self.too_long, self.in_code = [], None, [], False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.in_code = True  # 스크립트·스타일(지면 설정 JSON 등)은 기사 글이 아니다
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "article" and "item" in cls and "cmp" not in cls:
            self.cur = {"brief": "brief" in cls, "classes": set()}
            self.items.append(self.cur)
        if self.cur is not None:
            self.cur["classes"].update(cls)
            if tag == "a" and (a.get("href") or "").startswith("http"):
                self.cur["classes"].add("_link")
            if tag == "button" and a.get("data-fb"):
                self.cur["classes"].add("_fb_" + a["data-fb"])

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.in_code = False
        if tag == "article":
            self.cur = None

    def handle_data(self, data):
        if not self.in_code and len(data.strip()) > LEAD_MAX:
            self.too_long.append(data.strip())


def test_item_elements_and_no_body(tmp_path):
    index = make_site(tmp_path)
    html = index.read_text(encoding="utf-8")
    p = ItemParser()
    p.feed(html)
    full = [i for i in p.items if not i["brief"]]
    assert full
    for i in full:  # 제목·리드·매체·성향 배지·점수·원문 링크·피드백 2종 (연속 일수는 2일째 이상일 때 — 아래 테스트)
        assert {"hl", "lead", "src", "badge", "why", "orig-link", "_link", "_fb_more", "_fb_less"} <= i["classes"], i["classes"]
    assert not p.too_long, f"리드 상한({LEAD_MAX}자)을 넘는 글: {p.too_long[0][:40]}"
    # 이미지는 원 주소로만 (복사본·data URI 없음)
    assert "data:image" not in html
    assert not list((index.parent / "static").glob("**/*.jpg"))


def test_continuity_days_shown(tmp_path):
    arts, issues = build()
    all_arts = list(arts.values())
    df = title_df(all_arts)
    prev = [{"id": f"p{i}", "title": "x", "topic": "politics", "days": 2,
             "signature": issue_signature([arts[iss.rep_article]], df, len(all_arts))} for i, iss in enumerate(issues[:30])]
    html = make_site(tmp_path, previous=prev).read_text(encoding="utf-8")
    assert "3일째 보도" in html


def test_broken_photo_collapses(browser, tmp_path):
    """지연 로딩이라 사진은 그 쪽이 보일 때 불러온다 → 보이는 펼침면에서 깨진 사진 자리가 접히는지 본다."""
    index = make_site(tmp_path, broken_photo=True)
    ctx, page, _ = open_page(browser, index, 1180, 820)
    visible_figs = """() => [...document.querySelectorAll('#book figure.photo')].filter(f => {
        const r = f.getBoundingClientRect(); return r.width > 0 && r.right > 0 && r.left < innerWidth; }).length"""
    before = page.evaluate("[...document.querySelectorAll('#flow figure.photo')].length")
    page.wait_for_timeout(1500)
    figs = page.evaluate(visible_figs)
    assert before > 0  # 사진 자리가 있었는데
    pol = page.evaluate("[...document.querySelectorAll('img')].every(i => i.referrerPolicy === 'no-referrer' && i.loading === 'lazy')")
    ctx.close()
    assert figs == 0 and pol
