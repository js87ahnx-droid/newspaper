"""S9 피드백·S30c 관심 학습 — 실제 브라우저로.

기준 (project-plan.md S9·S30c):
- 피드백을 누른 뒤 다시 열면 배치가 바뀐다
- 한 분야에 "덜 보기"를 수십 번 눌러도 다양성 슬롯·1면 톱이 유지된다
- 설문은 저절로 뜨지 않는다 (설정 창의 "설문" 단추로만)
- 설정 창 슬라이더·키워드가 저장되고 지면이 다시 배치되며 중계 서버(/prefs)로 간다. 서버 값이 더 새것이면 받아 쓴다
- 예전 기기 값(delta)은 절대값으로 옮긴다, "기본값으로"
"""
import json
from pathlib import Path

import pytest

from pipeline.settings import load_config
from tests.test_render_browser import browser, make_site  # noqa: F401  (fixture 재사용)

CFG = load_config()

pw = pytest.importorskip("playwright.sync_api")

FLOW = """() => Object.fromEntries([...document.querySelectorAll('#flow section.sec')].map(s => [s.dataset.section,
    [...s.querySelectorAll(':scope > article.item[data-a]')].map(a => a.dataset.issue)]))"""
BOOK_IDS = "() => [...document.querySelectorAll('#book article.item[data-issue]')].map(a => a.dataset.issue)"


def open_(browser, index: Path, storage_init=None, route=None):
    ctx = browser.new_context(viewport={"width": 1180, "height": 820})
    if storage_init:
        ctx.add_init_script(storage_init)
    if route:
        ctx.route("https://reader.test/**", route)
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


def learn(page, topic, delta):
    """학습된 가중치를 바로 넣는다 (서버 값 + delta, 0~3) — 같은 단추를 다시 누르면 취소라(S24b) 여러 번 눌러 쌓을 수 없다."""
    page.evaluate(f"""() => {{ const p = NEWS_FB.prefs(), b = EDITION.topicWeights["{topic}"] || 0;
                             p.weights["{topic}"] = Math.max(0, Math.min(3, b + {delta}));
                             p.updated = new Date().toISOString(); localStorage.setItem('news.prefs2', JSON.stringify(p)); }}""")


def no_survey(page):
    if page.is_visible("#survey"):
        page.click('#survey [data-s="later"]')


def fake_reader(server):
    """가짜 중계 서버: server["prefs"] 를 GET 으로 돌려주고, POST 는 server["posted"] 에 쌓는다."""
    def route(r):
        cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "X-Reader-Key, Content-Type"}
        if r.request.method == "OPTIONS":
            return r.fulfill(status=204, headers=cors)
        assert r.request.headers.get("x-reader-key") == "k-test"
        if r.request.method == "POST":
            server.setdefault("posted", []).append(json.loads(r.request.post_data))
            server["prefs"] = server["posted"][-1]
        r.fulfill(status=200, headers={**cors, "Content-Type": "application/json"},
                  body=json.dumps({"ok": True, "prefs": server.get("prefs")}))
    return route


def reader_site(tmp_path, monkeypatch):
    monkeypatch.setenv("READER_URL", "https://reader.test")
    monkeypatch.setenv("READER_KEY", "k-test")
    return make_site(tmp_path)


def set_slider(page, topic, value):
    page.evaluate(f"""() => {{ const r = document.querySelector('#settings input[data-topic="{topic}"]');
        r.value = {value}; r.dispatchEvent(new Event('input', {{bubbles: true}}));
        r.dispatchEvent(new Event('change', {{bubbles: true}})); }}""")


def test_feedback_changes_layout_on_next_open(browser, tmp_path):
    index = make_site(tmp_path)
    ctx, page, errs = open_(browser, index)
    page.wait_for_timeout(800)
    no_survey(page)
    before = page.evaluate(FLOW)
    # 정치·안보 섹션의 보장 안 된 기사에 "덜 보기" → 정치 가중치 1.0 → 0 까지 학습된 것으로
    target = page.evaluate("""() => [...document.querySelectorAll('#flow section[data-section="politics"] > article.item')]
                                     .find(a => a.dataset.guaranteed === '0').dataset.issue""")
    press(page, target, "less")
    assert page.evaluate(FLOW) == before          # 누르는 즉시 지면이 튀지 않는다
    learn(page, "politics", -1.0)
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
        learn(page, t, -2.0)
    target = page.evaluate("""() => [...document.querySelectorAll('#flow section[data-section="briefs"] > article.item')]
                                     .find(a => a.dataset.guaranteed === '0' && a.dataset.topic === 'society').dataset.issue""")
    learn(page, "society", 0.75)                  # 사회 0.5 → 1.25 (기본보다 +0.75)
    reload_(page)
    moved = page.evaluate("window.NEWS_FB_LAST")
    after = page.evaluate(FLOW)
    ctx.close()
    assert 1 <= moved["promoted"] <= cap_room
    assert target in after["interest"] and target not in after["briefs"]
    assert len(after["interest"]) <= next(x.max_articles for x in CFG.sections if x.id == "interest")


def test_dozens_of_less_keep_diversity_and_top(browser, tmp_path):
    index = make_site(tmp_path)
    ctx, page, _ = open_(browser, index)
    page.wait_for_timeout(800)
    no_survey(page)
    top = page.evaluate("document.querySelector('#flow .fz-lead').dataset.issue")   # 1면 메인 기사 (S26)
    guaranteed = page.evaluate("[...document.querySelectorAll('#flow article.item[data-guaranteed=\"1\"]')].map(a => a.dataset.issue)")
    topics = page.evaluate("[...new Set([...document.querySelectorAll('#flow article.item')].map(a => a.dataset.topic))]")
    # 지면에 나온 모든 분야에 "덜 보기" 30번씩 (극단)
    for t in topics:
        learn(page, t, -7.5)
    reload_(page)
    book = set(page.evaluate(BOOK_IDS))
    first = page.evaluate("document.querySelector('#book .page[data-page=\"0\"] .fz-lead').dataset.issue")
    total = len(page.evaluate("[...document.querySelectorAll('#flow article.item[data-a]:not([data-reserve=\"1\"])')]"))
    ctx.close()
    assert first == top                            # 1면 톱 그대로
    assert set(guaranteed) - {top} <= book         # 다양성·연속 보장 기사 모두 지면에 (메인 기사는 1면 첫 쪽 — 위에서 확인)
    assert len(guaranteed) / total >= 0.3          # 다양성 30% 이상 유지
    assert total == CFG.editing.total_articles     # 기사가 지면에서 사라지지 않음 (단신으로만 내려감)


def test_press_again_cancels(browser, tmp_path):
    """S24b: 같은 단추를 다시 누르면 취소, 반대 단추로 바꾸면 앞 것을 되돌리고 새 것만."""
    index = make_site(tmp_path)
    ctx, page, errs = open_(browser, index)
    page.wait_for_timeout(800)
    no_survey(page)
    issue, topic = page.evaluate("(() => { const a = document.querySelector('#book article.item[data-topic]'); return [a.dataset.issue, a.dataset.topic]; })()")
    on = f"""() => [...document.querySelectorAll('#book [data-issue="{issue}"] [data-fb].pressed')].map(b => b.dataset.fb)"""
    delta = f"Math.round((NEWS_FB.weightOf(NEWS_FB.prefs(), '{topic}') - EDITION.topicWeights['{topic}']) * 100) / 100"
    press(page, issue, "more")
    first = (page.evaluate(on), page.evaluate(delta))
    press(page, issue, "more")
    undone = (page.evaluate(on), page.evaluate(delta), page.evaluate("JSON.parse(localStorage.getItem('news.pressed'))[EDITION.edition]"))
    press(page, issue, "more")
    press(page, issue, "less")
    switched = (page.evaluate(on), page.evaluate(delta))
    reload_(page)
    kept = page.evaluate(on)
    ctx.close()
    assert not errs, errs
    assert set(first[0]) == {"more"} and first[1] == 0.25
    assert undone[0] == [] and undone[1] == 0 and issue not in undone[2]
    assert set(switched[0]) == {"less"} and switched[1] == -0.25
    assert set(kept) == {"less"}                  # 다시 열어도 덜 보기만 표시


def test_no_survey_popup_but_button_still_works(browser, tmp_path):
    """S30c: 설문은 저절로 뜨지 않는다 (지난주에 답했어도). 설정 창의 "설문" 단추로 열고 저장하면 가중치·키워드에 반영."""
    index = make_site(tmp_path)
    ctx, page, errs = open_(browser, index, storage_init="try{localStorage.setItem('news.survey', JSON.stringify('2000-W01'));}catch(e){}")
    page.wait_for_timeout(1500)
    popped = page.is_visible("#survey")
    page.click('[data-act="settings"]')
    page.click('#settings [data-x="survey"]')
    page.check('#survey input[name="less"][value="entertainment_sports"]', force=True)
    page.check('#survey input[name="more"][value="science"]', force=True)
    page.fill('#survey input[name="kw"]', "원전, 배터리")
    page.click('#survey [data-s="save"]')
    p = page.evaluate("NEWS_FB.prefs()")
    base = page.evaluate("EDITION.topicWeights")
    ctx.close()
    assert not errs, errs
    assert not popped
    assert p["weights"]["entertainment_sports"] == max(0, round(base["entertainment_sports"] - 0.5, 2))
    assert p["weights"]["science"] == round(base["science"] + 0.5, 2)
    assert p["keywords"][-2:] == ["원전", "배터리"]


def test_sliders_save_relayout_and_push(browser, tmp_path, monkeypatch):
    """S30c: 슬라이더를 0 으로 → 저장·그 분야 기사가 단신으로·1.5초 모아 /prefs 로 보냄. 키워드 넣기·빼기도."""
    index = reader_site(tmp_path, monkeypatch)
    server = {}
    ctx, page, errs = open_(browser, index, route=fake_reader(server))
    page.wait_for_timeout(500)
    target = page.evaluate("""() => [...document.querySelectorAll('#flow section[data-section="politics"] > article.item')]
                                     .find(a => a.dataset.guaranteed === '0').dataset.issue""")
    page.click('[data-act="settings"]')
    rows = page.evaluate("document.querySelectorAll('#settings .wrow input[type=range]').length")
    set_slider(page, "politics", 0)
    label = page.text_content('#settings output[for="w-politics"]')
    page.fill('#settings .kwadd input', "원전")
    page.click('#settings .kwadd button')
    page.click('#settings .kwchip button[data-kw="0"]')   # 첫 키워드 빼기
    page.wait_for_timeout(2200)
    p = page.evaluate("NEWS_FB.prefs()")
    in_briefs = page.evaluate(f"""() => !!document.querySelector('#flow section[data-section="briefs"] > article.item[data-issue="{target}"]')""")
    pages = page.evaluate("NEWS.state().pages")
    defaults = page.evaluate("EDITION.defaultKeywords")
    ctx.close()
    assert not errs, errs
    assert rows == 10 and "안 봄" in label
    assert p["weights"]["politics"] == 0 and in_briefs and pages > 0
    assert p["keywords"] == defaults[1:] + ["원전"]
    last = server["posted"][-1]
    assert last["v"] == 1 and last["weights"]["politics"] == 0 and len(last["weights"]) == 10
    assert last["keywords"] == p["keywords"] and last["updated"] == p["updated"]
    assert len(server["posted"]) <= 2                 # 바꿀 때마다가 아니라 모아서 보냄


def test_newer_server_prefs_are_adopted(browser, tmp_path, monkeypatch):
    """S30c: 다른 기기에서 더 나중에 바꾼 값이 서버에 있으면 열 때 받아 쓰고 지면을 다시 배치한다. 이 기기 값이 더 새것이면 보낸다."""
    index = reader_site(tmp_path, monkeypatch)
    newer = {"v": 1, "weights": {"politics": 0.0}, "keywords": ["원전"], "updated": "2099-01-01T00:00:00.000Z"}
    server = {"prefs": newer}
    old_local = ("try{localStorage.setItem('news.prefs2', JSON.stringify({v:1, weights:{politics:2}, keywords:null,"
                 " updated:'2026-01-01T00:00:00.000Z'}));}catch(e){}")
    ctx, page, errs = open_(browser, index, storage_init=old_local, route=fake_reader(server))
    page.wait_for_function("NEWS_FB.prefs().updated === '2099-01-01T00:00:00.000Z'", timeout=5000)
    page.wait_for_timeout(300)
    politics = page.evaluate("""() => [...document.querySelectorAll('#flow section[data-section="politics"] > article.item')]
                                       .filter(a => a.dataset.guaranteed !== '1').length""")
    ctx.close()
    assert not errs, errs
    assert politics == 0 and "posted" not in server

    server2 = {"prefs": {**newer, "updated": "2000-01-01T00:00:00.000Z"}}
    ctx, page, errs = open_(browser, index, storage_init=old_local, route=fake_reader(server2))
    page.wait_for_timeout(1000)
    ctx.close()
    assert server2["posted"][-1]["weights"]["politics"] == 2   # 이 기기 값이 더 새것 → 보냄


def test_old_delta_migrates_and_reset(browser, tmp_path):
    """예전 기기 값(news.prefs 의 delta)은 절대값으로 옮기고, "기본값으로"는 interests.yaml 값으로."""
    index = make_site(tmp_path)
    old = "try{localStorage.setItem('news.prefs', JSON.stringify({delta:{politics:-0.75, science:0.5}, keywords:['원전']}));}catch(e){}"
    ctx, page, errs = open_(browser, index, storage_init=old)
    page.wait_for_timeout(500)
    p = page.evaluate("JSON.parse(localStorage.getItem('news.prefs2'))")
    base = page.evaluate("EDITION.topicWeights")
    page.click('[data-act="settings"]')
    page.click('#settings [data-x="reset"]')
    r = page.evaluate("NEWS_FB.prefs()")
    dflt = page.evaluate("[EDITION.defaultTopicWeights, EDITION.defaultKeywords]")
    ctx.close()
    assert not errs, errs
    assert p["weights"] == {"politics": round(base["politics"] - 0.75, 2), "science": round(base["science"] + 0.5, 2)}
    assert p["keywords"][-1] == "원전" and p["updated"]
    assert r["weights"] == {k: round(v, 2) for k, v in dflt[0].items()} and r["keywords"] == dflt[1]


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
