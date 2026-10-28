"""S31c·d 경제 해설 창·"이런 해설은 이제 필요 없어요" — 렌더와 실제 브라우저."""
import json

import pytest

from tests.test_feedback_browser import fake_reader, open_
from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)

DIVE = {"concepts": ["기준금리와 환율", "포워드 가이던스"],
        "theory": "통화정책은 시차를 두고 효과를 낸다 <b>태그는 글자로</b>.",
        "practice": "실제로는 다음 금리 경로를 시장이 어떻게 읽느냐가 더 크게 작용한다.",
        "analysis": ["원인: 누적 긴축 효과 점검.", "파급: 대출금리 상승세 둔화."],
        "watch": [{"what": "소비자물가", "why": "동결의 전제가 이어지는지 본다."}]}
ECON = ("economy", "industry", "semis_ai")


def with_econ(ed):
    """경제 분야 지면 기사(예비 제외)에 해설을 붙인다 — 실제 enrich 와 같은 자리(it.llm.econ)."""
    n = 0
    for ps in ed["sections"].values():
        for it in ps:
            if it.get("topic") in ECON and not it.get("reserve"):
                it["llm"] = {**it.get("llm", {}), "econ": DIVE}
                n += 1
    assert n > 0


def econ_site(tmp_path, monkeypatch=None):
    if monkeypatch:
        monkeypatch.setenv("READER_URL", "https://reader.test")
        monkeypatch.setenv("READER_KEY", "k-test")
    return make_site(tmp_path, mutate=with_econ)


def test_button_and_template_only_on_econ_items(tmp_path):
    html = econ_site(tmp_path).read_text(encoding="utf-8")
    assert html.count('data-econ>') == html.count('class="econ-src"') > 0
    assert "&lt;b&gt;태그는 글자로&lt;/b&gt;" in html and "<b>태그는 글자로</b>" not in html   # AI 글은 이스케이프
    plain = make_site(tmp_path / "p").read_text(encoding="utf-8")
    assert "data-econ>" not in plain


@pytest.mark.parametrize("w,h", [(1180, 820), (390, 844), (820, 1180), (1366, 1024)])
def test_window_opens_closes_and_layout_fits(browser, tmp_path, w, h):  # noqa: F811
    index = econ_site(tmp_path)
    ctx, page, errors = open_page(browser, index, w, h)
    st = page.evaluate("NEWS.state()")
    btn = page.evaluate("""() => { const b = [...document.querySelectorAll('#book .page .meta .econ-btn')]
        .find(b => b.getBoundingClientRect().width > 0 && b.closest('.page').style.visibility !== 'hidden'
              && !b.closest('.leaf[inert]')); return !!b; }""")
    if not btn:   # 첫 펼침에 경제 기사가 없으면 경제 면으로
        page.evaluate("""() => { const p = document.querySelector('#book .page .meta .econ-btn').closest('.page');
            NEWS.goTo(+p.dataset.page); }""")
        page.wait_for_timeout(200)
    page.evaluate("""() => { const b = [...document.querySelectorAll('#book .page .meta .econ-btn')]
        .find(b => b.getBoundingClientRect().width > 0 && !b.closest('.leaf[inert]')); b.focus(); b.click(); }""")
    page.wait_for_timeout(150)
    opened = page.evaluate("""() => ({open: !document.getElementById('reader').hidden,
        label: document.getElementById('reader').getAttribute('aria-label'),
        theory: document.querySelector('#reader .ev-tp .t p').textContent,
        concepts: [...document.querySelectorAll('#reader .ev-concepts .concept')].map(c => c.textContent),
        skip: !!document.querySelector('#reader .ev-skip-btn'),
        wide: document.querySelector('#reader .reader-panel').scrollWidth <= document.querySelector('#reader .reader-panel').clientWidth + 1,
        hscroll: document.documentElement.scrollWidth <= innerWidth})""")
    page.keyboard.press("Escape")
    after = page.evaluate("({open: !document.getElementById('reader').hidden, focus: document.activeElement.className})")
    ctx.close()
    assert not errors, errors
    assert st["overflow"] == [], st["overflow"]
    assert opened == {"open": True, "label": "경제 해설", "theory": DIVE["theory"], "concepts": DIVE["concepts"],
                      "skip": True, "wide": True, "hscroll": True}
    assert after == {"open": False, "focus": "econ-btn"}


def test_from_detail_window_and_back(browser, tmp_path):  # noqa: F811
    index = econ_site(tmp_path)
    ctx, page, errors = open_page(browser, index, 1180, 820)
    issue = page.evaluate("document.querySelector('#flow .meta .econ-btn').closest('[data-issue]').dataset.issue")
    page.evaluate(f"NEWS.openReader('{issue}')")
    page.click("#reader .reader-body .econ-btn")
    in_econ = page.evaluate("!!document.querySelector('#reader .econ-view')")
    page.click("#reader .econ-view .rv-back")
    back = page.evaluate("({econ: !!document.querySelector('#reader .econ-view'), item: !!document.querySelector('#reader .reader-body article.item')})")
    ctx.close()
    assert not errors, errors
    assert in_econ and back == {"econ": False, "item": True}


def test_not_needed_saves_known_pushes_and_undo(browser, tmp_path, monkeypatch):  # noqa: F811
    index = econ_site(tmp_path, monkeypatch)
    server = {}
    ctx, page, errs = open_(browser, index, route=fake_reader(server))
    issue = page.evaluate("document.querySelector('#flow .meta .econ-btn').closest('[data-issue]').dataset.issue")
    page.evaluate(f"NEWS.openReader('{issue}')")
    page.click("#reader .reader-body .econ-btn")
    page.click("#reader .ev-skip-btn")
    done = page.text_content("#reader .ev-done")
    known = page.evaluate("NEWS_FB.prefs().known")
    page.wait_for_timeout(1900)
    pushed = server["posted"][-1]["known"]
    page.click("#reader .ev-undo")
    undone = page.evaluate("NEWS_FB.prefs().known")
    page.click("#reader .ev-skip-btn")
    page.keyboard.press("Escape")
    page.click('[data-act="settings"]')
    chips = page.evaluate("[...document.querySelectorAll('#settings .knownchips .kwchip')].map(c => c.firstChild.textContent)")
    page.click('#settings .knownchips button[data-known="0"]')
    left = page.evaluate("NEWS_FB.prefs().known")
    ctx.close()
    assert not errs, errs
    assert known == DIVE["concepts"] and pushed == DIVE["concepts"] and "기준금리와 환율" in done
    assert undone == []
    assert chips == DIVE["concepts"] and left == DIVE["concepts"][1:]


def test_known_survives_server_adoption(browser, tmp_path, monkeypatch):  # noqa: F811
    """다른 기기에서 더 나중에 표시한 아는 개념도 받아 쓴다 (관심 학습값과 같은 길)."""
    index = econ_site(tmp_path, monkeypatch)
    server = {"prefs": {"v": 1, "weights": {}, "keywords": ["HBM"], "known": ["포워드 가이던스"], "updated": "2099-01-01T00:00:00.000Z"}}
    ctx, page, errs = open_(browser, index, route=fake_reader(server))
    page.wait_for_function("NEWS_FB.prefs().known.length === 1", timeout=5000)
    knows = page.evaluate("[NEWS_FB.knows('포워드 가이던스'), NEWS_FB.knows('기준금리와 환율')]")
    ctx.close()
    assert not errs, errs
    assert knows == [True, False]
    assert json.dumps(server).count("posted") == 0
