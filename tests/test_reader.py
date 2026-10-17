"""S17 원문 재배열 보기 — 중계 서버(worker/) 연결.

기준 (project-plan.md S17):
- 키 없는 요청·허용목록 밖 주소 거부 (worker/test — 실제 Workers 런타임으로)
- 저장소·지면에 본문 없음 (기존 검사 유지 + 중계 서버에 저장소 바인딩 없음)
- 실패 시 원문 링크로 자연스럽게 넘어감 (실제 브라우저)
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import reader
from pipeline.settings import ROOT, load_sources
from tests.test_render_browser import browser, make_site  # noqa: F401  (픽스처)

WORKER = ROOT / "worker"
G = "https://news.google.com/rss/articles/CBMiAAA?oc=5"


def test_allowlist_in_sync_with_sources():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "reader_domains.py"), "--check"], capture_output=True, text=True,
                       encoding="utf-8")
    assert r.returncode == 0, r.stdout
    doms = json.loads((WORKER / "src" / "domains.json").read_text(encoding="utf-8"))
    for s in load_sources().sources:
        if s.enabled:
            assert s.site, f"{s.name}: site 없음"
    assert "news.google.com" not in doms and not any(d.endswith("google.com") for d in doms)


def test_config_needs_url_and_key(monkeypatch):
    monkeypatch.delenv("READER_URL", raising=False)
    monkeypatch.delenv("READER_KEY", raising=False)
    assert reader.config() is None
    monkeypatch.setenv("READER_URL", "https://r.example.workers.dev/")
    assert reader.config() is None                       # 키 없음
    monkeypatch.setenv("READER_KEY", "  k1  ")
    assert reader.config() == {"url": "https://r.example.workers.dev", "key": "k1"}
    monkeypatch.setenv("READER_URL", "http://r.example.workers.dev")
    assert reader.config() is None                       # 평문 http 는 로컬 시험만


def test_read_url_skips_blocked_sources_and_unresolved_google():
    srcs = load_sources()
    blocked = [s.name for s in srcs.sources if not s.reader]
    assert {"New York Times", "Wall Street Journal", "Reuters", "AP", "SCMP"} <= set(blocked)
    ru = reader.read_url_fn({"read_urls": {G: "https://www.joongang.co.kr/article/1"}}, srcs)
    assert ru("https://www.chosun.com/a/", "조선일보") == "https://www.chosun.com/a/"
    assert ru("https://www.nytimes.com/a.html", "New York Times") == ""
    assert ru(G, "중앙일보") == "https://www.joongang.co.kr/article/1"
    assert ru(G.replace("AAA", "BBB"), "중앙일보") == ""      # 못 푼 Google 주소는 그냥 원문 링크


def test_page_urls_cover_items_groups_and_opinion():
    ed = {"sections": {"front": [{"url": "u1", "stance": {"lean": [{"articles": [{"url": "u2"}, {"url": "u3"}, {"url": "u4"}]}]}}]},
          "compare": [],
          "opinion": {"compare": [{"groups": [{"editorials": [{"url": "o1"}]}]}], "editorials": [{"url": "o2"}], "columns": [{"url": "o3"}]}}
    assert reader.page_urls(ed) == ["u1", "u2", "u3", "o1", "o2", "o3"]   # 그룹은 보이는 2건만


def test_worker_has_no_storage():
    """D16: 중계 서버는 아무것도 저장하지 않는다 — 저장소 바인딩 없음, 응답 no-store, 요청 기록 끔."""
    toml = (WORKER / "wrangler.toml").read_text(encoding="utf-8")
    for b in ("kv_namespaces", "r2_buckets", "d1_databases", "durable_objects", "queues", "[cache]"):
        assert b not in toml
    assert re.search(r"\[observability\]\s*\nenabled = false", toml)
    src = (WORKER / "src" / "index.js").read_text(encoding="utf-8")
    assert "no-store" in src and "caches." not in src and "console.log" not in src


def test_reader_key_not_in_public_static_files(tmp_path, monkeypatch):
    """키는 지면 HTML(암호화됨) 안에만 — 정적 파일(app.js 등)에는 없다."""
    monkeypatch.setenv("READER_URL", "https://reader.example.workers.dev")
    monkeypatch.setenv("READER_KEY", "secret-key-xyz")
    index = make_site(tmp_path)
    assert "secret-key-xyz" in index.read_text(encoding="utf-8")
    for f in (index.parent / "static").rglob("*"):
        if f.is_file() and f.suffix in (".js", ".css", ".json", ".webmanifest"):
            assert "secret-key-xyz" not in f.read_text(encoding="utf-8", errors="ignore"), f


@pytest.mark.skipif(not (WORKER / "node_modules" / "wrangler").exists() or not shutil.which("node"),
                    reason="worker/ 의존성 없음 (cd worker && npm install)")
def test_worker_rejects_without_key_or_outside_allowlist():
    r = subprocess.run(["node", "--test", "test/reader.test.mjs"], cwd=WORKER, capture_output=True, text=True,
                       encoding="utf-8", timeout=240)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    assert "# fail 0" in r.stdout or "ℹ fail 0" in r.stdout


# ---------- 실제 브라우저: 누르면 읽기 화면, 실패하면 원문 링크 ----------

ARTICLE = {"ok": True, "url": "https://www.chosun.com/x/", "title": "재배열된 제목", "site": "조선일보", "published": "2026-10-16T05:00:00+09:00",
           "images": [{"src": "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", "caption": "사진 설명"}],
           "paragraphs": ["첫 문단 <b>태그는 글자로</b>", "둘째 문단", "셋째 문단"], "via": "본문 칸", "chars": 30}


def _open(browser, tmp_path, monkeypatch, handler, configured=True):  # noqa: F811
    if configured:
        monkeypatch.setenv("READER_URL", "https://reader.test")
        monkeypatch.setenv("READER_KEY", "k-test")
    else:
        monkeypatch.delenv("READER_URL", raising=False)
        monkeypatch.delenv("READER_KEY", raising=False)
    index = make_site(tmp_path)
    ctx = browser.new_context(viewport={"width": 1180, "height": 820}, reduced_motion="reduce")
    ctx.add_init_script("try{localStorage.setItem('news.survey', '2099-W01');}catch(e){}")
    seen = []

    def route(r):
        seen.append({"url": r.request.url, "key": r.request.headers.get("x-reader-key"), "method": r.request.method})
        cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "X-Reader-Key"}
        if r.request.method == "OPTIONS":
            return r.fulfill(status=204, headers=cors)
        status, body = handler(r.request.url)
        if isinstance(body, str):   # 플랫폼 오류 페이지
            return r.fulfill(status=status, headers={**cors, "Content-Type": "text/html"}, body=body)
        r.fulfill(status=status, headers={**cors, "Content-Type": "application/json"}, body=json.dumps(body))

    ctx.route("https://reader.test/**", route)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(index.as_uri())
    page.wait_for_function("window.NEWS && window.NEWS.state().pages > 0")
    return ctx, page, errors, seen


def _first_link(page):
    return page.evaluate("""() => { const a = document.querySelector('#book .page a[data-read]');
        a.scrollIntoView(); return a ? a.getAttribute('data-read') : null; }""")


def test_click_headline_opens_reader_view(browser, tmp_path, monkeypatch):  # noqa: F811
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u: (200, ARTICLE))
    target = _first_link(page)
    assert target
    page.evaluate("document.querySelector('#book .page a[data-read]').click()")
    page.wait_for_selector(".readview .rv-p")
    v = page.evaluate("""() => { const v = document.querySelector('.readview');
        return {title: v.querySelector('.rv-title').textContent, ps: [...v.querySelectorAll('.rv-p')].map(p => p.textContent),
                bold: v.querySelectorAll('.rv-p b').length, photo: v.querySelectorAll('.rv-photo img').length,
                foot: v.querySelector('.rv-foot a').href, open: !document.getElementById('reader').hidden}; }""")
    assert v["open"] and v["title"] == "재배열된 제목"
    assert v["ps"][0] == "첫 문단 <b>태그는 글자로</b>" and v["bold"] == 0      # 원문 HTML 은 글자로만
    assert v["photo"] == 1 and v["foot"] == "https://www.chosun.com/x/"
    get = [s for s in seen if s["method"] == "GET"]
    assert len(get) == 1 and get[0]["key"] == "k-test"
    from urllib.parse import parse_qs, urlsplit
    assert parse_qs(urlsplit(get[0]["url"]).query)["url"] == [target]
    page.keyboard.press("Escape")
    assert page.evaluate("document.getElementById('reader').hidden")
    assert errors == []
    ctx.close()


@pytest.mark.parametrize("status,body", [(422, {"ok": False, "reason": "본문을 찾지 못함"}), (502, {"ok": False, "reason": "원문 http 403"})])
def test_failure_falls_back_to_original_link(browser, tmp_path, monkeypatch, status, body):  # noqa: F811
    calls = []
    ctx, page, errors, _ = _open(browser, tmp_path, monkeypatch, lambda u: (calls.append(u), (status, body))[1])
    target = _first_link(page)
    page.evaluate("document.querySelector('#book .page a[data-read]').click()")
    page.wait_for_selector(".readview .rv-orig-big")
    v = page.evaluate("""() => ({msg: document.querySelector('.rv-status').textContent,
        href: document.querySelector('.rv-orig-big').href, target: document.querySelector('.rv-orig-big').target,
        focused: document.activeElement.classList.contains('rv-orig-big')})""")
    assert body["reason"] in v["msg"] and v["href"] == target and v["target"] == "_blank" and v["focused"]
    assert len(calls) == 1                                   # 매체 실패는 다시 부르지 않는다
    assert errors == []
    ctx.close()


def test_without_relay_links_stay_plain(browser, tmp_path, monkeypatch):  # noqa: F811
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u: (200, ARTICLE), configured=False)
    assert page.evaluate("document.querySelectorAll('a[data-read]').length") == 0
    assert page.evaluate("window.EDITION.reader") is None
    assert seen == [] and errors == []
    ctx.close()


def test_retries_once_on_platform_503(browser, tmp_path, monkeypatch):  # noqa: F811
    """Cloudflare 가 깨어날 때 내는 503 오류 페이지(JSON 아님)는 한 번만 다시 부른다. 매체 실패(JSON 502)는 다시 부르지 않는다."""
    calls = []

    def handler(u):
        calls.append(u)
        return (503, "<!DOCTYPE html>Error 1102") if len(calls) == 1 else (200, ARTICLE)

    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, handler)
    page.evaluate("document.querySelector('#book .page a[data-read]').click()")
    page.wait_for_selector(".readview .rv-p")
    assert len(calls) == 2 and errors == []
    ctx.close()
