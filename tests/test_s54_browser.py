"""S54c ④ 자세히 창 안의 전문 칸 (시안 C). 가짜 중계 서버(reader.test)로."""
from __future__ import annotations

import json

from tests.test_reader import ARTICLE, _open
from tests.test_render_browser import browser  # noqa: F401  (픽스처)

READ = """() => { const b = document.querySelector('#reader .reader-body');
  const ft = b.querySelector('.ft'), alt = b.querySelector('.ft-alt');
  return { ft: !!ft, h: ft ? ft.querySelector('.ft-h').textContent : null, ps: ft ? [...ft.querySelectorAll('.rv-p')].map(p => p.textContent) : [],
           status: ft ? ft.querySelector('.rv-status').textContent : null, fail: !!(ft && ft.querySelector('.rv-fail')),
           pay: !!(ft && ft.querySelector('.ft-pay')), tr: ft ? [...ft.querySelectorAll('.rv-tab')].map(x => x.textContent) : [],
           alt: alt && !alt.hidden ? [...alt.querySelectorAll('button')].map(x => x.getAttribute('data-src')) : null }; }"""


def _gets(seen):
    return [s for s in seen if s["method"] == "GET"]


def _open_title(page, sel):
    """조건에 맞는 메타 줄 "원문" 단추를 가진 지면 기사의 제목을 누른다 → issue id."""
    return page.evaluate("""(sel) => { const b = document.querySelector('#flow article.item > .meta .orig-btn' + sel);
        if (!b) return null; const iid = b.closest('article').getAttribute('data-issue'); NEWS.openReader(iid); return iid; }""", sel)


def _close(page):
    page.evaluate("() => document.querySelector('[data-reader-close]').click()")


def test_title_shows_full_text_once_per_url(browser, tmp_path, monkeypatch):
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE))
    iid = _open_title(page, '[data-lang="ko"]:not([data-read=""])')
    assert iid
    page.wait_for_selector("#reader .ft .rv-p")
    r = page.evaluate(READ)
    assert r["ft"] and r["h"].startswith("전문 — ") and r["ps"][0] == "첫 문단 <b>태그는 글자로</b>" and not r["fail"] and r["tr"] == []
    assert len(_gets(seen)) == 1
    _close(page)
    page.evaluate("(i) => NEWS.openReader(i)", iid)                       # 다시 열기 — 같은 주소는 다시 안 받음
    page.wait_for_selector("#reader .ft .rv-p")
    page.evaluate("() => document.querySelector('#reader .reader-body .meta .orig-btn').click()")   # 창 안 "원문" — 같은 결과
    page.wait_for_selector(".readview .rv-p")
    assert len(_gets(seen)) == 1
    stored = page.evaluate("() => JSON.stringify(Object.assign({}, localStorage)) + JSON.stringify(Object.assign({}, sessionStorage))")
    assert "둘째 문단" not in stored and not errors, errors
    ctx.close()


def test_inflight_shared_when_reopened(browser, tmp_path, monkeypatch):
    pending = []

    def handler(u, b=None):
        return 200, ARTICLE
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, handler)
    # 첫 요청을 붙잡아 두었다가 나중에 응답
    ctx.unroute("https://reader.test/**")
    cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "X-Reader-Key, Content-Type"}

    def hold(r):
        if r.request.method == "OPTIONS":
            return r.fulfill(status=204, headers=cors)
        if r.request.url.split("?")[0].endswith("/prefs"):
            return r.fulfill(status=200, headers={**cors, "Content-Type": "application/json"}, body='{"ok": true, "prefs": null}')
        pending.append(r)
    ctx.route("https://reader.test/**", hold)
    iid = _open_title(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_timeout(300)
    _close(page)
    page.evaluate("(i) => NEWS.openReader(i)", iid)
    page.wait_for_timeout(300)
    assert len(pending) == 1                                              # 받는 중 닫고 다시 열어도 1건
    assert page.evaluate("() => document.querySelector('#reader .ft .rv-status').textContent") == "전문을 불러오는 중…"
    pending[0].fulfill(status=200, headers={**cors, "Content-Type": "application/json"}, body=json.dumps(ARTICLE))
    page.wait_for_selector("#reader .ft .rv-p")
    assert not errors, errors
    ctx.close()


def test_failure_shows_link_and_retries_next_open(browser, tmp_path, monkeypatch):
    calls = []
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch,
                                    lambda u, b=None: (calls.append(u), (502, {"ok": False, "reason": "원문 http 403"}))[1])
    iid = _open_title(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_selector("#reader .ft .rv-fail")
    r = page.evaluate(READ)
    assert "원문 http 403" in r["status"] and page.evaluate("() => !!document.querySelector('#reader .ft .rv-link-big')")
    _close(page)
    page.evaluate("(i) => NEWS.openReader(i)", iid)
    page.wait_for_selector("#reader .ft .rv-fail")
    assert len(calls) == 2 and not errors                                  # 실패는 남기지 않아 다시 받음
    ctx.close()


def _blocked_and_paywall(ed):
    intl = [i for i in ed["sections"]["international"] if not i.get("reserve")]
    a, b = intl[0], intl[1]
    a["source"], a["url"] = "New York Times", "https://www.nytimes.com/2026/10/16/world/x.html"
    a["articles"] = [{"id": "n1", "source": "New York Times", "url": a["url"], "title": "막힌 기사", "lang": "en", "paywall": True},
                     {"id": "c1", "source": "조선일보", "url": "https://www.chosun.com/x/alt1/", "title": "대체 기사 하나", "lang": "ko", "paywall": False},
                     {"id": "r1", "source": "Reuters", "url": "https://www.reuters.com/x", "title": "막힌 다른 기사", "lang": "en", "paywall": False},
                     {"id": "c2", "source": "BBC", "url": "https://www.bbc.com/news/x", "title": "Alt two", "lang": "en", "paywall": False}]
    b["source"], b["url"] = "Der Spiegel", "https://www.spiegel.de/ausland/x"
    b["view"] = b.get("view") or {}


def test_blocked_shows_alternatives_and_paywall_note(browser, tmp_path, monkeypatch):
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE), mutate=_blocked_and_paywall)
    _open_title(page, '[data-href*="world/x.html"]')
    r = page.evaluate(READ)
    assert not r["ft"] and r["alt"] == ["조선일보", "BBC"], r                 # 막힌 매체(Reuters) 빼고, 매체당 하나
    page.evaluate("() => document.querySelector('#reader .ft-alt button').click()")   # 대체 기사 → 원문 창
    page.wait_for_selector(".readview .rv-p")
    assert len(_gets(seen)) == 1
    _close(page)
    _open_title(page, '[data-href*="spiegel.de/ausland/x"]')
    page.wait_for_selector("#reader .ft .rv-p")
    r = page.evaluate(READ)
    assert r["pay"] and r["tr"] == ["한국어로 번역"]                          # 유료 안내, 외국어는 단추만
    assert not [s for s in seen if s["url"].endswith("/translate")]
    assert page.evaluate("() => [...document.querySelectorAll('#book .page-inner .ft-alt')].every(x => x.offsetHeight === 0)")
    assert not errors, errors
    ctx.close()


def test_translate_button_once(browser, tmp_path, monkeypatch):
    def handler(u, body=None):
        if u.endswith("/translate"):
            return 200, {"ok": True, "texts": ["번역됨"] * len(body["texts"])}
        return 200, ARTICLE
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, handler, mutate=_blocked_and_paywall)
    iid = _open_title(page, '[data-href*="spiegel.de/ausland/x"]')
    page.wait_for_selector("#reader .ft .rv-tab")
    page.evaluate("() => document.querySelector('#reader .ft .rv-tab').click()")
    page.wait_for_function("() => document.querySelector('#reader .ft .rv-p').textContent === '번역됨'")
    _close(page)
    page.evaluate("(i) => NEWS.openReader(i)", iid)
    page.wait_for_selector("#reader .ft .rv-tab")
    page.evaluate("() => document.querySelector('#reader .ft .rv-tab').click()")
    page.wait_for_function("() => document.querySelector('#reader .ft .rv-p').textContent === '번역됨'")
    assert len([s for s in seen if s["url"].endswith("/translate")]) == 1 and not errors
    ctx.close()


def test_no_full_section_without_relay_or_for_china_opinion(browser, tmp_path, monkeypatch):
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE), configured=False)
    _open_title(page, "")
    assert not page.evaluate(READ)["ft"] and not errors
    ctx.close()


def test_horizontal_scroll_none_phone(browser, tmp_path, monkeypatch):
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE))
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(600)
    _open_title(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_selector("#reader .ft .rv-p")
    m = page.evaluate("() => ({ sw: document.scrollingElement.scrollWidth, iw: innerWidth, pw: document.querySelector('#reader .reader-panel').scrollWidth, pc: document.querySelector('#reader .reader-panel').clientWidth })")
    assert m["sw"] <= m["iw"] and m["pw"] <= m["pc"] + 1 and not errors, m
    ctx.close()


import pytest  # noqa: E402

from tests.test_render_browser import make_site, open_page  # noqa: E402


@pytest.mark.parametrize("w,h", [(1180, 820), (1366, 1024), (390, 844)])
def test_opinion_titles_fit_no_drop(browser, tmp_path, w, h):
    """논평면 외국어 글에 한국어 줄이 늘어도 지면에서 빠지는 글 0, 넘침 0 (S54g)."""
    from tests.test_s54 import _op_edition

    def mutate(ed):
        _op_edition(ed)
        for k in range(12):   # 사설·칼럼을 넉넉히 — 쪽 나누기가 실제로 일어나게
            for kind in ("editorials", "columns"):
                row = dict(ed["opinion"][kind][-1])
                row["id"] = f"x{kind}{k}"
                row["title"] = row["title"] + f" {k}"
                ed["opinion"][kind].append(row)
    index = make_site(tmp_path, mutate=mutate)
    ctx, page, errors = open_page(browser, index, w, h)
    st = page.evaluate("() => NEWS.state()")
    m = page.evaluate("""() => { const want = [...document.querySelectorAll('#flow section[data-section=opinion] a[data-art]')].map(a => a.textContent);
      const got = new Set([...document.querySelectorAll('#book .page.sec-opinion a[data-art]')].map(a => a.textContent));
      return { want: want.length, missing: want.filter(t => !got.has(t)).length,
               ko: document.querySelectorAll('#book .page.sec-opinion .ko-sub').length }; }""")
    assert not errors and not st["overflow"], (errors, st["overflow"])
    assert m["ko"] > 0 and m["missing"] == 0, m
    ctx.close()


def test_alt_button_uses_its_own_title_and_noread_message(browser, tmp_path, monkeypatch):
    def mutate(ed):
        _blocked_and_paywall(ed)
        intl = [i for i in ed["sections"]["international"] if not i.get("reserve")]
        c = intl[2]   # reader 가능 매체인데 Google 주소를 못 푼 기사
        c["source"], c["url"] = "조선일보", "https://news.google.com/rss/articles/unresolved-x"
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (502, {"ok": False, "reason": "원문 http 403"}), mutate=mutate)
    _open_title(page, '[data-href*="world/x.html"]')
    assert "막아 두었습니다" in page.evaluate("() => document.querySelector('#reader .ft-alt .ft-why').textContent")
    page.evaluate("() => document.querySelector('#reader .ft-alt button').click()")       # 대체 기사도 실패
    page.wait_for_selector(".readview .rv-link-big")
    t = page.evaluate("() => document.querySelector('.readview .rv-title').textContent")
    assert t == "대체 기사 하나", t                                                         # 막힌 원래 기사 제목이 아님
    _close(page)
    _open_title(page, '[data-href*="unresolved-x"]')
    page.evaluate("() => document.querySelector('#reader .reader-body .meta .orig-btn').click()")
    page.wait_for_selector(".readview .rv-link-big")
    assert "원문 주소를 찾지 못했습니다" in page.evaluate("() => document.querySelector('.readview .rv-status').textContent")
    assert not errors, errors
    ctx.close()


def test_reader_window_translation_cached(browser, tmp_path, monkeypatch):
    def handler(u, body=None):
        if u.endswith("/translate"):
            return 200, {"ok": True, "texts": ["번역됨"] * len(body["texts"])}
        return 200, ARTICLE
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, handler, mutate=_blocked_and_paywall)
    for _ in range(2):
        page.evaluate("() => document.querySelector('#flow article.item > .meta .orig-btn[data-href*=\"spiegel.de/ausland/x\"]').click()")
        page.wait_for_selector(".readview .rv-tab")
        _close(page)
    assert len([s for s in seen if s["url"].endswith("/translate")]) == 1 and not errors
    ctx.close()


def test_no_full_section_for_china_and_wide_no_scroll(browser, tmp_path, monkeypatch):
    from tests.test_china_browser import add_china
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE), mutate=add_china)
    page.evaluate("() => NEWS.openReader(document.querySelector('#flow article.cn-view').getAttribute('data-issue'))")
    page.wait_for_selector("#reader:not([hidden]) .cn-view")
    assert not page.evaluate("() => !!document.querySelector('#reader .ft, #reader .ft-alt:not([hidden])')")
    _close(page)
    _open_title(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_selector("#reader .ft .rv-p")
    m = page.evaluate("() => ({ sw: document.scrollingElement.scrollWidth, iw: innerWidth })")
    assert m["sw"] <= m["iw"] and not errors, m
    ctx.close()
