"""S38b 설정 창 탭 + 편집 리뷰 — 실제 브라우저로.

기준 (project-plan.md S38b):
- 탭 셋 [관심도 | 편집 리뷰 | 편집 기준], 관심도는 예전 창 그대로
- 편집 리뷰: 면별 목록(1면만 펼침), 글자 단추 [적절][위로][아래로][빼기], 이모지 없음, 방향을 고르면 메모 칸, 다시 누르면 취소
- 고른 것이 다시 열어도 남고, 서버(/reviews)로 점수·분야와 함께 간다. 서버 없이도 오류 없음
- 휴대폰·패드에서 넘침 없음. 지면 기사의 점수 펼침은 그대로
"""
import json
import re
from pathlib import Path

import pytest

from tests.test_feedback_browser import open_, reader_site, reload_
from tests.test_render_browser import browser, make_site  # noqa: F401  (fixture 재사용)

pw = pytest.importorskip("playwright.sync_api")

EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def fake_reviews(server):
    def route(r):
        cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "X-Reader-Key, Content-Type"}
        if r.request.method == "OPTIONS":
            return r.fulfill(status=204, headers=cors)
        assert r.request.headers.get("x-reader-key") == "k-test"
        path = r.request.url.split("?")[0]
        if path.endswith("/reviews") and r.request.method == "POST":
            server.setdefault("posted", []).append(json.loads(r.request.post_data))
            body = {"ok": True}
        elif path.endswith("/reviews"):
            server["gets"] = server.get("gets", 0) + 1
            body = {"ok": True, "reviews": server.get("reviews", []), "reset": None}
        else:
            body = {"ok": True, "prefs": None}
        r.fulfill(status=200, headers={**cors, "Content-Type": "application/json"}, body=json.dumps(body))
    return route


def open_review(page):
    page.click('[data-act="settings"]')
    page.click('#settings [data-tab="review"]')
    page.wait_for_selector('#settings [data-pane="review"] .rv')


def test_tabs_and_review_list(browser, tmp_path):
    index = make_site(tmp_path)
    ctx, page, errs = open_(browser, index)
    page.click('[data-act="settings"]')
    tabs = page.eval_on_selector_all("#settings [data-tab]", "bs => bs.map(b => b.textContent)")
    assert tabs == ["관심도", "편집 리뷰", "편집 기준"]
    assert page.is_visible('#settings input[data-topic]')          # 관심도 = 예전 창
    page.click('#settings [data-tab="review"]')
    assert not page.is_visible('#settings input[data-topic]')
    secs = page.eval_on_selector_all("#settings .rvsec", "ds => ds.map(d => d.open)")
    assert secs and secs[0] is True and not any(secs[1:])          # 1면만 펼침
    n = page.evaluate("EDITION.review.length")
    assert page.eval_on_selector_all("#settings .rv", "x => x.length") == n
    labels = page.eval_on_selector('#settings .rv', "r => [...r.querySelectorAll('.rvb button')].map(b => b.textContent)")
    assert labels == ["적절", "위로", "아래로", "빼기"]
    assert not EMOJI.search(page.inner_text("#settings"))
    assert page.eval_on_selector_all("#book details.why", "x => x.length") > 0   # 지면 점수 펼침은 그대로
    assert errs == []
    ctx.close()


def test_choose_persist_cancel_no_server(browser, tmp_path):
    index = make_site(tmp_path)
    ctx, page, errs = open_(browser, index)
    open_review(page)
    first = page.get_attribute('#settings .rvsec[open] .rv', "data-id")
    row = f'#settings .rv[data-id="{first}"]'
    page.click(f'{row} [data-rv="down"]')
    assert page.is_visible(f"{row} .rvmemo")                        # 방향을 고르면 메모 칸
    page.fill(f"{row} .rvmemo", "해외 단발 사건")
    page.press(f"{row} .rvmemo", "Tab")
    assert "서버 주소가 없어" in page.inner_text("#settings .rvstat")
    reload_(page)
    open_review(page)                                               # 마지막 탭(편집 리뷰)이 남아 있어도 다시 누르면 그대로
    assert page.get_attribute(f'{row} [data-rv="down"]', "aria-pressed") == "true"
    assert page.input_value(f"{row} .rvmemo") == "해외 단발 사건"
    page.click(f'{row} [data-rv="down"]')                           # 다시 누르면 취소
    assert page.eval_on_selector_all(f"{row} .on", "x => x.length") == 0
    assert not page.is_visible(f"{row} .rvmemo")
    page.click(f'{row} [data-rv="ok"]')
    assert not page.is_visible(f"{row} .rvmemo")                    # 적절은 메모 없음
    assert page.evaluate("Object.keys(NEWS_EDIT.reviews()).length") == 1
    assert errs == []
    ctx.close()


def test_sent_to_server_with_scores(browser, tmp_path, monkeypatch):
    index = reader_site(tmp_path, monkeypatch)
    server = {}
    ctx, page, errs = open_(browser, index, route=fake_reviews(server))
    open_review(page)
    assert server.get("gets") == 1                                  # 이 기기에 없으면 서버 것을 한 번 본다
    first = page.get_attribute('#settings .rvsec[open] .rv', "data-id")
    page.click(f'#settings .rv[data-id="{first}"] [data-rv="up"]')
    page.fill(f'#settings .rv[data-id="{first}"] .rvmemo', "더 중요")
    page.press(f'#settings .rv[data-id="{first}"] .rvmemo', "Tab")
    page.wait_for_function("document.querySelector('#settings .rvstat').textContent.includes('서버에 저장')", timeout=6000)
    body = server["posted"][-1]
    ed = page.evaluate("EDITION.edition")
    assert body["v"] == 1 and body["edition"] == ed
    it = body["items"][first]
    assert it["verdict"] == "up" and it["memo"] == "더 중요" and it["section"] == "front" and it["rank"] == 1
    assert set(it["scores"]) == {"attention", "importance", "headline", "continuity", "interest", "final"}
    assert all(0 <= v <= 1 for v in it["scores"].values())
    assert errs == []
    ctx.close()


def test_pull_from_other_device(browser, tmp_path, monkeypatch):
    index = reader_site(tmp_path, monkeypatch)
    server = {}
    ctx, page, errs = open_(browser, index, route=fake_reviews(server))
    ed, first = page.evaluate("[EDITION.edition, EDITION.review[0].id]")
    server["reviews"] = [{"v": 1, "edition": ed, "items": {first: {"verdict": "drop", "memo": "다른 기기"}}}]
    open_review(page)
    page.wait_for_selector(f'#settings .rv[data-id="{first}"] [data-rv="drop"].on')
    assert page.input_value(f'#settings .rv[data-id="{first}"] .rvmemo') == "다른 기기"
    assert errs == []
    ctx.close()


@pytest.mark.parametrize("w,h", [(390, 844), (375, 667), (768, 1024), (1180, 820)])
def test_no_overflow(browser, tmp_path, w, h):
    index = make_site(tmp_path)
    ctx = browser.new_context(viewport={"width": w, "height": h})
    page = ctx.new_page()
    page.goto(index.as_uri())
    page.wait_for_function("window.NEWS && NEWS.state().pages > 0", timeout=20000)
    open_review(page)
    page.click('#settings .rv [data-rv="up"]')
    for t in ("prefs", "review", "rules"):
        page.click(f'#settings [data-tab="{t}"]')
        over = page.evaluate("""() => { const c = document.querySelector('#settings .card'), r = c.getBoundingClientRect();
            const bad = [...c.querySelectorAll('*')].filter(e => { const b = e.getBoundingClientRect();
              return b.width && (b.right > r.right + 1 || b.left < r.left - 1); }).map(e => e.className || e.tagName);
            return {bad, page: document.documentElement.scrollWidth - innerWidth, inView: r.left >= -1 && r.right <= innerWidth + 1}; }""")
        assert over["bad"] == [] and over["inView"], (w, t, over)
    ctx.close()


def open_rules(page):
    page.click('[data-act="settings"]')
    page.click('#settings [data-tab="rules"]')
    page.wait_for_selector('#settings [data-pane="rules"] .rules')


def test_rules_tab_defaults(browser, tmp_path):
    """학습값이 없으면 config.yaml 값 그대로, "아직 자동 조정 없음". 서버가 없으면 되돌리기 단추 없음."""
    from pipeline.settings import load_config
    cfg = load_config(learned=False)
    index = make_site(tmp_path)
    ctx, page, errs = open_(browser, index)
    open_rules(page)
    text = page.inner_text('#settings [data-pane="rules"]')
    assert "아직 자동 조정 없음" in text
    assert f"주목도 {cfg.weights.attention:.2f}" in text and f"중요도 {cfg.weights.importance:.2f}" in text
    assert f"머리기사 비중 {cfg.weights.front_headline:.2f}" in text
    assert f"{round(cfg.editing.diversity_ratio * 100)}%" in text and f"{cfg.editing.continuity_min_days}일 이상" in text
    assert "기본" not in page.inner_text('#settings .rules p')                      # 바뀐 값 표시 없음
    assert page.query_selector('#settings [data-rl="reset"]') is None
    assert not EMOJI.search(text)
    assert errs == []
    ctx.close()


def test_rules_tab_learned_and_reset(browser, tmp_path, monkeypatch):
    """학습값이 있으면 그 값(기본값 함께)과 조정 내역, 되돌리기는 확인 뒤 /reviews/reset 으로."""
    from pipeline import review
    from pipeline.settings import ROOT, load_config
    cfg = load_config(learned=False)
    lp = tmp_path / "editing-learned.json"
    lp.write_text(json.dumps({"v": 1, "week": "2026-W45", "edition": "2026-11-03", "reviews": 14,
                              "weights": {"importance": 0.345}, "topic_importance": {"politics": 1.1},
                              "changes": [{"kind": "weight", "key": "importance", "label": "중요도", "from": 0.3, "to": 0.345}],
                              "history": [{"week": "2026-W44", "reviews": 11, "changes": []},
                                          {"week": "2026-W45", "reviews": 14, "changes": []}]}), encoding="utf-8")
    orig = review.learned_path
    monkeypatch.setattr(review, "learned_path", lambda root: lp if Path(root).resolve() == Path(ROOT).resolve() else orig(root))
    index = reader_site(tmp_path, monkeypatch)
    server = {}
    posted = []

    def route(r):
        if r.request.url.endswith("/reviews/reset"):
            posted.append(r.request.method)
            return r.fulfill(status=200, headers={"Access-Control-Allow-Origin": "*", "Content-Type": "application/json"},
                             body='{"ok":true,"reset":"x"}')
        return fake_reviews(server)(r)
    ctx, page, errs = open_(browser, index, route=route)
    assert page.evaluate("EDITION.editing.w.importance") == 0.345                   # 지면 편집도 학습값으로
    open_rules(page)
    text = page.inner_text('#settings [data-pane="rules"]')
    assert "중요도 0.34 (기본 " + f"{cfg.weights.importance:.2f})" in text
    assert "정치·안보 1.10 (기본 1.00)" in text
    assert "2026-W45" in text and "리뷰 14건" in text and "중요도 0.30 → 0.34" in text
    page.on("dialog", lambda d: d.dismiss())
    page.click('#settings [data-rl="reset"]')
    assert posted == []                                                             # 취소하면 안 보냄
    ctx.close()
    ctx, page, errs = open_(browser, index, route=route)
    page.on("dialog", lambda d: d.accept())
    open_rules(page)
    page.click('#settings [data-rl="reset"]')
    page.wait_for_function("document.querySelector('#settings .rlstat').textContent.includes('요청했습니다')", timeout=5000)
    assert posted == ["POST"]
    assert errs == []
    ctx.close()
