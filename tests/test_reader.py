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


def test_page_urls_cover_analysis_and_picks():
    """S18: 분석·해설 면·지정 칼럼 주소도 푼다 (지정 칼럼은 Google 뉴스로 받는다 — 빠져서 원문 창이 못 열렸다)."""
    ed = {"sections": {}, "compare": [], "analysis": [{"url": "a1"}], "picks": [{"url": "p1"}]}
    assert reader.page_urls(ed) == ["a1", "p1"]


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


def _open(browser, tmp_path, monkeypatch, handler, configured=True, mutate=None):  # noqa: F811
    if configured:
        monkeypatch.setenv("READER_URL", "https://reader.test")
        monkeypatch.setenv("READER_KEY", "k-test")
    else:
        monkeypatch.delenv("READER_URL", raising=False)
        monkeypatch.delenv("READER_KEY", raising=False)
    index = make_site(tmp_path, mutate=mutate)
    ctx = browser.new_context(viewport={"width": 1180, "height": 820}, reduced_motion="reduce")
    ctx.add_init_script("try{localStorage.setItem('news.survey', '2099-W01');}catch(e){}")
    seen = []

    def route(r):
        seen.append({"url": r.request.url, "key": r.request.headers.get("x-reader-key"), "method": r.request.method})
        cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "X-Reader-Key, Content-Type"}
        if r.request.method == "OPTIONS":
            return r.fulfill(status=204, headers=cors)
        status, body = handler(r.request.url, json.loads(r.request.post_data) if r.request.method == "POST" else None)
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


def _click_orig(page, where):
    """조건(where: data-lang·data-read 등 CSS)에 맞는 지면 기사의 "원문" 단추를 누르고 그 단추의 속성을 돌려준다."""
    return page.evaluate("""(sel) => { const b = document.querySelector('#book .page .meta button.orig-btn' + sel);
        if (!b) return null; b.scrollIntoView(); b.click();
        return {read: b.getAttribute('data-read'), href: b.getAttribute('data-href'), lang: b.getAttribute('data-lang'),
                src: b.getAttribute('data-src'), lead: (b.closest('article').querySelector('.lead') || {}).textContent || ''}; }""", where)


def _view(page):
    return page.evaluate("""() => { const v = document.querySelector('.readview');
        return {title: v.querySelector('.rv-title').textContent, ps: [...v.querySelectorAll('.rv-p')].map(p => p.textContent),
                bold: v.querySelectorAll('.rv-p b').length, photo: v.querySelectorAll('.rv-photo img').length,
                status: v.querySelector('.rv-status').textContent, link: (v.querySelector('.rv-top .rv-link') || {}).href,
                big: (v.querySelector('.rv-link-big') || {}).href, tabs: [...v.querySelectorAll('.rv-tab')].map(b => b.textContent),
                open: !document.getElementById('reader').hidden, label: document.getElementById('reader').getAttribute('aria-label')}; }""")


def test_title_opens_ai_detail_and_link_is_plain(browser, tmp_path, monkeypatch):  # noqa: F811
    """제목 → AI 정리(자세히 창), "링크" → 그냥 새 탭 링크 (가로채지 않음)."""
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE))
    issue = page.evaluate("""() => { const a = document.querySelector('#book .page .hl a[data-detail]'); a.scrollIntoView(); a.click();
        return a.closest('[data-issue]').getAttribute('data-issue'); }""")
    st = page.evaluate("""() => ({label: document.getElementById('reader').getAttribute('aria-label'),
        issue: (document.querySelector('.reader-body article.item') || {getAttribute: () => null}).getAttribute('data-issue'),
        more: document.querySelectorAll('[data-more]').length})""")
    assert st["label"] == "기사 자세히" and st["issue"] == issue and st["more"] == 0     # "자세히" 단추는 없앴다
    link = page.evaluate("""() => { const a = document.querySelector('#book .page .meta a.link-btn');
        return {href: a.href, target: a.target, art: a.hasAttribute('data-art'), detail: a.hasAttribute('data-detail')}; }""")
    assert link["target"] == "_blank" and link["href"].startswith("http") and not link["art"] and not link["detail"]
    assert [s for s in seen if s["method"] != "OPTIONS"] == [] and errors == []
    ctx.close()


def test_orig_button_opens_reader_view(browser, tmp_path, monkeypatch):  # noqa: F811
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE))
    b = _click_orig(page, '[data-lang="ko"]:not([data-read=""])')
    assert b and b["read"]
    page.wait_for_selector(".readview .rv-p")
    v = _view(page)
    assert v["open"] and v["label"] == "원문 보기" and v["title"] == "재배열된 제목"
    assert v["ps"][0] == "첫 문단 <b>태그는 글자로</b>" and v["bold"] == 0      # 원문 HTML 은 글자로만
    assert v["photo"] == 1 and v["link"] == b["href"] and v["tabs"] == []         # 한국 매체는 번역 없음
    get = [s for s in seen if s["method"] == "GET"]
    assert len(get) == 1 and get[0]["key"] == "k-test"
    from urllib.parse import parse_qs, urlsplit
    assert parse_qs(urlsplit(get[0]["url"]).query)["url"] == [b["read"]]
    page.keyboard.press("Escape")
    assert page.evaluate("document.getElementById('reader').hidden")
    assert errors == []
    ctx.close()


def test_foreign_article_gets_korean_translation(browser, tmp_path, monkeypatch):  # noqa: F811
    posts = []

    def handler(u, body=None):
        if u.endswith("/translate"):
            posts.append(body)
            return 200, {"ok": True, "texts": ["[번역] " + t for t in body["texts"]]}
        return 200, {**ARTICLE, "title": "English title", "paragraphs": ["First.", "Second."]}

    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, handler)
    b = _click_orig(page, '[data-lang="en"]:not([data-read=""])')
    assert b
    page.wait_for_selector(".readview .rv-tab")
    v = _view(page)
    assert posts[-1]["lang"] == "en" and posts[-1]["texts"] == ["English title", "First.", "Second."]
    assert v["title"] == "[번역] English title" and v["ps"] == ["[번역] First.", "[번역] Second."] and v["tabs"] == ["한국어", "원문"]
    page.click(".readview .rv-tab >> text=원문")
    assert _view(page)["ps"] == ["First.", "Second."]
    page.click(".readview .rv-tab >> text=한국어")
    assert _view(page)["ps"][0] == "[번역] First."
    post = [s for s in seen if s["method"] == "POST"]
    assert len(post) == 1 and post[0]["key"] == "k-test" and errors == []
    ctx.close()


def test_blocked_source_opens_window_with_feed_content(browser, tmp_path, monkeypatch):  # noqa: F811
    """중계 서버가 못 여는 매체(NYT 등)도 새 탭이 아니라 원문 창: 피드 내용·안내·링크 + 번역(제목·리드)."""
    def handler(u, body=None):
        if u.endswith("/translate"):
            return 200, {"ok": True, "texts": ["번역됨"] * len(body["texts"])}
        return 200, ARTICLE

    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, handler)
    b = _click_orig(page, '[data-src="New York Times"]')
    assert b and b["read"] == ""
    page.wait_for_selector(".readview .rv-link-big")
    v = _view(page)
    assert v["open"] and "막아 두었습니다" in v["status"] and v["big"] == b["href"] and v["link"] == b["href"]
    assert [s for s in seen if s["method"] == "GET"] == []                       # 막힌 매체는 부르지 않는다
    page.wait_for_selector(".readview .rv-tab")                                   # 제목·리드 번역
    assert _view(page)["title"] == "번역됨"
    assert errors == []
    ctx.close()


@pytest.mark.parametrize("status,body", [(422, {"ok": False, "reason": "본문을 찾지 못함"}), (502, {"ok": False, "reason": "원문 http 403"})])
def test_failure_falls_back_to_feed_content(browser, tmp_path, monkeypatch, status, body):  # noqa: F811
    calls = []
    ctx, page, errors, _ = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (calls.append(u), (status, body))[1])
    b = _click_orig(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_selector(".readview .rv-link-big")
    v = _view(page)
    assert body["reason"] in v["status"] and v["big"] == b["href"]
    if b["lead"].strip():
        assert b["lead"].strip() in v["ps"]
    assert len(calls) == 1                                   # 매체 실패는 다시 부르지 않는다 (한국 매체라 번역도 없음)
    assert errors == []
    ctx.close()


def test_without_relay_orig_still_opens_window(browser, tmp_path, monkeypatch):  # noqa: F811
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE), configured=False)
    assert page.evaluate("[...document.querySelectorAll('[data-read]')].every(e => e.getAttribute('data-read') === '')")
    assert page.evaluate("window.EDITION.reader") is None
    b = _click_orig(page, "")
    page.wait_for_selector(".readview .rv-link-big")
    assert _view(page)["big"] == b["href"]
    assert seen == [] and errors == []
    ctx.close()


def test_retries_once_on_platform_503(browser, tmp_path, monkeypatch):  # noqa: F811
    """Cloudflare 가 깨어날 때 내는 503 오류 페이지(JSON 아님)는 한 번만 다시 부른다. 매체 실패(JSON 502)는 다시 부르지 않는다."""
    calls = []

    def handler(u, body=None):
        calls.append(u)
        return (503, "<!DOCTYPE html>Error 1102") if len(calls) == 1 else (200, ARTICLE)

    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, handler)
    _click_orig(page, '[data-lang="ko"]:not([data-read=""])')
    page.wait_for_selector(".readview .rv-p")
    assert len(calls) == 2 and errors == []
    ctx.close()


def test_small_links_open_reader_window(browser, tmp_path, monkeypatch):  # noqa: F811
    """입장 차이의 작은 제목 링크는 원문 창으로."""
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE))
    n = page.evaluate("""() => { const a = document.querySelector('#book .page .grp a[data-art]'); if (!a) return 0;
        a.scrollIntoView(); a.click(); return 1; }""")
    assert n, "지면에 입장 차이 링크가 없음"
    page.wait_for_selector(".readview")
    assert _view(page)["label"] == "원문 보기" and errors == []
    ctx.close()


# ---------- S17c 사진 큰 판, S17d 언어가 다른 같은 사건 ----------

def test_larger_photo_rewrites_known_thumbnails():
    from pipeline.render import larger_photo
    assert larger_photo("https://ichef.bbci.co.uk/ace/standard/240/cpsprodpb/x/live/a.jpg") == \
        "https://ichef.bbci.co.uk/ace/standard/976/cpsprodpb/x/live/a.jpg"
    assert larger_photo("https://flexible.img.hani.co.kr/flexible/normal/300/180/imgdb/a.webp") == \
        "https://flexible.img.hani.co.kr/flexible/normal/970/582/imgdb/a.webp"
    assert larger_photo("https://img.yna.co.kr/photo/cms/2026/01/21/54/PCM1_P2.jpg") == "https://img.yna.co.kr/photo/cms/2026/01/21/54/PCM1_P4.jpg"
    for u in ("https://dimg.donga.com/a.png", "https://i.guim.co.uk/img/a.jpg?width=700&s=1", None, ""):
        assert larger_photo(u) == u


def _issue(iid, title, headline=None):
    it = {"issue_id": iid, "title": title, "articles": [{"id": iid + "a", "source": "S" + iid, "country": "KR"}], "lead": ""}
    if headline:
        it["llm"] = {"analysis": {"headline": headline, "summary": headline}}
    return it


def test_same_event_two_step_and_merge_moves_analysis():
    from pipeline.llm import merge_duplicates, same_event_groups
    items = [_issue("en", "Elon Musk unveils Tesla's flying car"), _issue("ko", "테슬라 하늘 나는 스포츠카", "테슬라, 나는 스포츠카 시연"),
             _issue("pk", "파키스탄 학교 붕괴", "파키스탄 학교 붕괴"), _issue("ro", "흑해 선박 드론 피격", "흑해 선박 드론 피격")]
    asked = []

    def ask(prompt):
        asked.append(prompt)
        if len(asked) == 1:
            return {"groups": [[0, 1], [2, 3]]}      # 1단계: 틀린 묶음(2,3)이 섞임
        return {"groups": [[0, 1], [0, 2]]}           # 2단계: (0,2) 는 제안에 없던 묶음 → 무시
    groups, st = same_event_groups(items, ask)
    assert st == "ok" and groups["en"] == groups["ko"] and "pk" not in groups and "ro" not in groups
    assert "원제목" not in asked[0] and "Elon Musk" in asked[0]          # 분석 없는 이슈도 원제목으로 후보에
    ed = {"sections": {"international": [items[0]], "economy": [items[1]]}}
    merged = merge_duplicates(ed, groups)
    assert merged == [("en", "ko")] and ed["sections"]["economy"] == []
    host = ed["sections"]["international"][0]
    assert host["llm"]["analysis"]["headline"] == "테슬라, 나는 스포츠카 시연"   # 분석이 남는 쪽으로 옮겨감
    assert {a["id"] for a in host["articles"]} == {"ena", "koa"}


def test_same_event_failure_keeps_edition():
    from pipeline.llm import same_event_groups
    items = [_issue("a", "A", "가"), _issue("b", "B", "나")]
    assert same_event_groups(items, lambda p: None) == ({}, "응답 없음")
    calls = iter([{"groups": [[0, 1]]}, None])
    assert same_event_groups(items, lambda p: next(calls)) == ({}, "검증 응답 없음")


def test_related_opinions_by_issue_including_merged():
    from pipeline.render import related_opinions
    op = {"editorials": [{"issue_id": "a", "url": "u1", "kind": "editorial", "lean": "진보", "source": "경향", "title": "사설1"},
                         {"issue_id": None, "url": "u2", "kind": "editorial", "lean": "보수", "source": "조선", "title": "무관"}],
          "columns": [{"issue_id": "a", "url": "u3", "kind": "column", "lean": "보수", "source": "동아", "title": "칼럼"},
                      {"issue_id": "b", "url": "u4", "kind": "column", "lean": "중도", "source": "NYT", "title": "합쳐진 쪽"}]}
    rel = related_opinions(op)
    assert [o["title"] for o in rel["a"]] == ["사설1", "칼럼"] and rel["a"][0]["cls"] == "pro"   # 사설이 먼저
    assert "None" not in rel and None not in rel and related_opinions(None) == {}
    # 같은 사건으로 합쳐진 이슈(b → a)에 연결된 것도 그 기사 곁에
    ids = ["a", *["b"]]
    assert [o["title"] for i in ids for o in rel.get(i, [])] == ["사설1", "칼럼", "합쳐진 쪽"]


# ---------- S19a 표기, S19b 매체별 관점 원문 ----------
def test_stance_links_match_source_names():
    from pipeline.render import stance_links
    it = {"articles": [{"source": "New York Times", "url": "n1"}, {"source": "조선일보", "url": "c1"}, {"source": "조선일보", "url": "c2"},
                       {"source": "Guardian", "url": "g1"}]}
    an = {"stances": [{"source": "NYT", "view": "a"}, {"source": "조선일보", "view": "b"}, {"source": "조선", "view": "c"},
                      {"source": "The Guardian", "view": "d"}, {"source": "Le Monde", "view": "e"}, {"source": "", "view": "f"},
                      {"source": "뉴욕타임스", "view": "g"}, {"source": "가디언", "view": "h"}]}
    got = [(s["view"], s["article"]["url"] if s["article"] else None) for s in stance_links(it, an)]
    assert got == [("a", "n1"), ("b", "c1"), ("c", "c1"), ("d", "g1"), ("e", None), ("f", None),
                   ("g", "n1"), ("h", "g1")]   # 대표 = 첫 기사, 한글 이름도
    assert stance_links(it, None) == [] and stance_links(it, {"stances": []}) == []


def test_headline_and_coverage_labels(tmp_path):
    from pipeline.render import headline_label
    assert headline_label({"BBC": [1, "feed"], "조선일보": [1, "naver_a1"]}) == "1면 조선 / 헤드라인 BBC"
    html = make_site(tmp_path).read_text(encoding="utf-8")
    assert re.search(r"\d+개 매체·\d+개국 보도", html) and not re.search(r"매체 \d+ · 국가 \d+", html)
    assert "머리 " not in re.sub(r"<script.*?</script>", "", html, flags=re.S)


def _with_stances(out):
    for ps in out["sections"].values():
        for it in ps[:2]:
            srcs = list(dict.fromkeys(a["source"] for a in it["articles"]))
            it["llm"] = {"analysis": {"headline": "분석 제목", "summary": "요약", "background": "", "points": [], "brief": "",
                                      "stances": [{"source": s, "view": f"{s} 관점"} for s in srcs] + [{"source": "없는 매체", "view": "x"}]}}


def test_stance_view_orig_opens_that_outlets_article(browser, tmp_path, monkeypatch):  # noqa: F811
    """매체별 관점 줄의 "원문" → 그 매체 기사 원문 창 (S19b). 맞는 기사가 없는 줄엔 단추 없음."""
    ctx, page, errors, seen = _open(browser, tmp_path, monkeypatch, lambda u, b=None: (200, ARTICLE), mutate=_with_stances)
    info = page.evaluate("""() => { const lis = [...document.querySelectorAll('#flow .an-views li')];
        const b = document.querySelector('#book .page .an-views button.view-orig:not([data-read=""])');
        const r = {rows: lis.length, btn: lis.filter(l => l.querySelector('button.view-orig')).length,
                   nobtn: lis.filter(l => l.textContent.startsWith('없는 매체')).every(l => !l.querySelector('button')),
                   srcOk: lis.every(l => { const x = l.querySelector('button'); return !x || l.querySelector('b').textContent === x.dataset.src; })};
        if (b) { b.scrollIntoView(); b.click(); r.read = b.dataset.read; }
        return r; }""")
    assert info["rows"] > info["btn"] > 0 and info["nobtn"] and info["srcOk"], info
    assert info.get("read"), "지면에 원문 단추가 보이는 관점 줄이 없음"
    page.wait_for_selector(".readview .rv-p")
    assert _view(page)["label"] == "원문 보기" and errors == []
    from urllib.parse import parse_qs, urlsplit
    get = [s for s in seen if s["method"] == "GET"]
    assert parse_qs(urlsplit(get[-1]["url"]).query)["url"] == [info["read"]]
    ctx.close()
