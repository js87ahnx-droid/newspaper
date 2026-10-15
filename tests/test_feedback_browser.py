"""S9 피드백·주간 설문 — 실제 브라우저로.

기준 (project-plan.md S9):
- 피드백을 누른 뒤 다시 열면 배치가 바뀐다
- 한 분야에 "덜 보기"를 수십 번 눌러도 다양성 슬롯·1면 톱이 유지된다
- 설문 카드는 주 1회만 뜬다
- (D3) 학습된 가중치를 파일로 내보낸다
"""
import json
from pathlib import Path

import pytest

from tests.test_render_browser import browser, make_site  # noqa: F401  (fixture 재사용)

pw = pytest.importorskip("playwright.sync_api")

FLOW = """() => Object.fromEntries([...document.querySelectorAll('#flow section.sec')].map(s => [s.dataset.section,
    [...s.querySelectorAll(':scope > article.item[data-a]')].map(a => a.dataset.issue)]))"""
BOOK_IDS = "() => [...document.querySelectorAll('#book article.item[data-issue]')].map(a => a.dataset.issue)"


def open_(browser, index: Path, storage_init=None):
    ctx = browser.new_context(viewport={"width": 1180, "height": 820}, accept_downloads=True)
    if storage_init:
        ctx.add_init_script(storage_init)
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(index.as_uri())
    page.wait_for_function("window.NEWS && NEWS.state().pages > 0", timeout=20000)
    return ctx, page, errs


def reload_(page):
    page.reload()
    page.wait_for_function("window.NEWS && NEWS.state().pages > 0", timeout=20000)


def press(page, issue, kind, times=1):
    for _ in range(times):
        page.evaluate(f"""() => document.querySelector('#book [data-issue="{issue}"] [data-fb="{kind}"]').click()""")


def no_survey(page):
    if page.is_visible("#survey"):
        page.click('#survey [data-s="later"]')


def test_feedback_changes_layout_on_next_open(browser, tmp_path):
    index = make_site(tmp_path)
    ctx, page, errs = open_(browser, index)
    page.wait_for_timeout(800)
    no_survey(page)
    before = page.evaluate(FLOW)
    # 정치·안보 섹션의 보장 안 된 기사에 "덜 보기" 4번 → 정치 가중치 1.0 → 0
    target = page.evaluate("""() => [...document.querySelectorAll('#flow section[data-section="politics"] > article.item')]
                                     .find(a => a.dataset.guaranteed === '0').dataset.issue""")
    press(page, target, "less", 4)
    assert page.evaluate(FLOW) == before          # 누르는 즉시 지면이 튀지 않는다
    reload_(page)
    after = page.evaluate(FLOW)
    ctx.close()
    assert not errs, errs
    assert after != before
    assert target not in after.get("politics", []) and target in after["briefs"]


def test_more_feedback_promotes_within_cap(browser, tmp_path):
    index = make_site(tmp_path)
    ctx, page, _ = open_(browser, index)
    page.wait_for_timeout(800)
    no_survey(page)
    cap_room = page.evaluate("Math.max(0, EDITION.interestCap - EDITION.interestCounted)")
    assert cap_room > 0
    # 관심면을 채운 분야를 "덜 보기"로 비우고, 다른 분야(사회) 단신에 "더 보기"
    interest_topics = page.evaluate("""() => [...new Set([...document.querySelectorAll('#flow section[data-section="interest"] > article.item')]
                                              .map(a => a.dataset.topic))]""")
    for t in interest_topics:
        iss = page.evaluate(f"document.querySelector('#book article.item[data-topic=\"{t}\"]').dataset.issue")
        press(page, iss, "less", 8)
    target = page.evaluate("""() => [...document.querySelectorAll('#flow section[data-section="briefs"] > article.item')]
                                     .find(a => a.dataset.guaranteed === '0' && a.dataset.topic === 'society').dataset.issue""")
    press(page, target, "more", 3)                # 사회 0.5 → 1.25 (기본보다 +0.75)
    reload_(page)
    moved = page.evaluate("window.NEWS_FB_LAST")
    after = page.evaluate(FLOW)
    ctx.close()
    assert 1 <= moved["promoted"] <= cap_room
    assert target in after["interest"] and target not in after["briefs"]
    assert len(after["interest"]) <= 6


def test_dozens_of_less_keep_diversity_and_top(browser, tmp_path):
    index = make_site(tmp_path)
    ctx, page, _ = open_(browser, index)
    page.wait_for_timeout(800)
    no_survey(page)
    top = page.evaluate("document.querySelector('#flow article.item[data-top=\"1\"]').dataset.issue")
    guaranteed = page.evaluate("[...document.querySelectorAll('#flow article.item[data-guaranteed=\"1\"]')].map(a => a.dataset.issue)")
    topics = page.evaluate("[...new Set([...document.querySelectorAll('#flow article.item')].map(a => a.dataset.topic))]")
    # 지면에 나온 모든 분야에 "덜 보기" 30번씩 (극단)
    for t in topics:
        issue = page.evaluate(f"document.querySelector('#book article.item[data-topic=\"{t}\"]')?.dataset.issue || null")
        if issue:
            press(page, issue, "less", 30)
    reload_(page)
    book = set(page.evaluate(BOOK_IDS))
    first = page.evaluate("document.querySelector('#book article.item').dataset.issue")
    total = len(page.evaluate("[...document.querySelectorAll('#flow article.item[data-a]')]"))
    ctx.close()
    assert first == top                            # 1면 톱 그대로
    assert set(guaranteed) <= book                 # 다양성·연속 보장 기사 모두 지면에
    assert len(guaranteed) / total >= 0.3          # 다양성 30% 이상 유지
    assert total == 40                             # 기사가 지면에서 사라지지 않음 (단신으로만 내려감)


def test_survey_once_per_week(browser, tmp_path):
    index = make_site(tmp_path)
    ctx, page, _ = open_(browser, index)
    page.wait_for_selector("#survey", timeout=3000)
    page.click('#survey [data-s="later"]')
    reload_(page)
    page.wait_for_timeout(1000)
    assert not page.is_visible("#survey")          # 같은 주에는 다시 안 뜸
    # 지난주에 답한 것으로 바꾸면 다시 뜬다
    page.evaluate("localStorage.setItem('news.survey', JSON.stringify('2000-W01'))")
    reload_(page)
    page.wait_for_selector("#survey", timeout=3000)
    # 답을 저장하면 가중치·키워드에 반영되고, 이번 주에는 다시 안 뜬다
    page.check('#survey input[name="less"][value="entertainment_sports"]', force=True)
    page.check('#survey input[name="more"][value="science"]', force=True)
    page.fill('#survey input[name="kw"]', "원전, 배터리")
    page.click('#survey [data-s="save"]')
    p = page.evaluate("NEWS_FB.prefs()")
    week = page.evaluate("JSON.parse(localStorage.getItem('news.survey'))")
    this_week = page.evaluate("NEWS_FB.isoWeek(new Date())")
    ctx.close()
    assert p["delta"]["entertainment_sports"] == -0.5 and p["delta"]["science"] == 0.5
    assert p["keywords"] == ["원전", "배터리"]
    assert week == this_week


def test_export_learned_weights(browser, tmp_path):
    index = make_site(tmp_path)
    ctx, page, _ = open_(browser, index)
    page.wait_for_timeout(800)
    no_survey(page)
    issue = page.evaluate("document.querySelector('#book article.item[data-topic=\"politics\"]').dataset.issue")
    press(page, issue, "less", 4)
    page.click('[data-act="settings"]')
    with page.expect_download() as dl:
        page.click('#settings [data-x="export"]')
    data = json.loads(Path(dl.value.path()).read_text(encoding="utf-8"))
    ctx.close()
    assert dl.value.suggested_filename == "interests-learned-2026-10-16.json"
    assert "politics" in data["less"] and "politics" not in data["topics"]
    assert data["learned_delta"]["politics"] == -1.0
    assert set(data) >= {"topics", "less", "keywords"}


def test_works_without_storage(browser, tmp_path):
    """사생활 보호 모드 등으로 localStorage 를 못 쓰면 학습 없이 그대로 보여 준다."""
    index = make_site(tmp_path)
    block = "Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); } });"
    ctx, page, errs = open_(browser, index, storage_init=block)
    page.wait_for_timeout(800)
    no_survey(page)
    issue = page.evaluate("document.querySelector('#book article.item').dataset.issue")
    press(page, issue, "less")
    pages = page.evaluate("NEWS.state().pages")
    ctx.close()
    assert pages > 0 and not errs, errs
