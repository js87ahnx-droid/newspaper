"""S10 발행 폴더와 공개 전 검사."""
import json
import subprocess
import sys
from pathlib import Path

from pipeline.edit import arrange, choose, edition_to_json
from pipeline.interest import build_interest_table
from pipeline.publish import publish
from pipeline.score import score_issues
from pipeline.settings import ROOT, load_config, load_interests, load_sources
from tests.test_edit import build


def edition(d="2026-10-16"):
    cfg, interests = load_config(), load_interests()
    arts, issues = build()
    sc = score_issues(issues, arts, cfg, build_interest_table(interests), [])
    placed, st = choose(sc, cfg, interests)
    return edition_to_json(arrange(placed, cfg, interests, arts), d, arts, st)


def test_publish_layout_and_archive(tmp_path):
    site = tmp_path / "docs"
    cfg, interests, sources = load_config(), load_interests(), load_sources()
    for d in ("2026-10-15", "2026-10-16"):
        files = publish(edition(d), cfg, interests, sources, site)
    assert [f.relative_to(site).as_posix() for f in files] == ["index.html", "archive/2026-10-16/index.html", "archive/index.html"]
    assert (site / ".nojekyll").exists() and (site / "static" / "app.js").exists()
    arch = (site / "archive" / "2026-10-16" / "index.html").read_text(encoding="utf-8")
    assert 'href="../../static/app.css?v=' in arch and '"base": "../../"' in arch
    listing = (site / "archive" / "index.html").read_text(encoding="utf-8")
    assert listing.index("10월 16일자 뉴스") < listing.index("10월 15일자 뉴스")  # 최신이 위


def test_archive_shows_lead_title_from_history(tmp_path):
    """지난 호 목록의 하이라이트 = 1면 메인 제목 (2026-11-06). 기록은 data/history 에 남고 기록 없는 호는 비어 있다."""
    from pipeline.render import lead_record

    site, hist = tmp_path / "docs", tmp_path / "history"
    hist.mkdir()
    cfg, interests, sources = load_config(), load_interests(), load_sources()
    (site / "archive" / "2026-10-14").mkdir(parents=True)     # 기록이 없던 지난 호
    (hist / "2026-10-15.json").write_text(json.dumps({"v": 2, "edition": "2026-10-15", "issues": [], "lead_title": "어제 <메인> 제목"}, ensure_ascii=False), encoding="utf-8")
    (site / "archive" / "2026-10-15").mkdir()
    (hist / "2026-10-16.json").write_text(json.dumps({"v": 2, "edition": "2026-10-16", "issues": [{"id": "x"}]}), encoding="utf-8")
    ed = edition()
    publish(ed, cfg, interests, sources, site, history_dir=hist)
    lead = lead_record(ed, cfg, interests, sources)
    title = lead["title"]
    saved = json.loads((hist / "2026-10-16.json").read_text(encoding="utf-8"))
    assert title and saved["lead_title"] == title and saved["issues"] == [{"id": "x"}]
    assert saved["lead_note"]["why"] and "korea" in saved["lead_note"]["signals"]   # 판정 기록 (S42)
    listing = (site / "archive" / "index.html").read_text(encoding="utf-8")
    assert title in listing and "어제 &lt;메인&gt; 제목" in listing and "<메인>" not in listing
    row = listing[listing.index("10월 14일자 뉴스"):]
    assert '<span class="hi"></span>' in row[:row.index("</li>")]


def test_archive_row_stays_one_line(tmp_path):
    """긴 제목은 칸 너비에 맞춰 한 줄로 줄이고, 좁은 화면에서는 요일을 뺀다. 가로로 밀리지 않는다."""
    import pytest
    pw = pytest.importorskip("playwright.sync_api")
    from pipeline.render import render_archive_index
    from datetime import date

    site = tmp_path / "site"
    (site / "archive").mkdir(parents=True)
    (site / "static").mkdir()
    (site / "static" / "app.css").write_text((ROOT / "static" / "app.css").read_text(encoding="utf-8"), encoding="utf-8")
    long = "아주 긴 1면 메인 제목이 칸 너비를 넘어가는 경우를 확인하기 위한 문장입니다 " * 3
    (site / "archive" / "index.html").write_text(
        render_archive_index([date(2026, 11, 6), date(2026, 11, 5)], highlights={"2026-11-06": long}), encoding="utf-8")
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        for w, h, day in [(1180, 820, True), (390, 844, False)]:
            page = b.new_page(viewport={"width": w, "height": h})
            page.goto((site / "archive" / "index.html").as_uri(), wait_until="domcontentloaded")
            m = page.evaluate("""() => { const a = document.querySelector('.archive li a'), hi = a.querySelector('.hi'), n = a.querySelector('.name');
                return {sw: document.scrollingElement.scrollWidth - innerWidth, h: a.getBoundingClientRect().height, cut: hi.scrollWidth > hi.clientWidth,
                        nameLines: n.getClientRects().length, nh: n.getBoundingClientRect().height, hi: hi.getBoundingClientRect().width,
                        day: getComputedStyle(a.querySelector('.day')).display !== 'none'}; }""")
            assert m["sw"] <= 1 and m["cut"] and m["hi"] > 100 and m["nh"] < 30 and m["day"] == day, (w, m)
            if w == 1180:
                page.screenshot(path=str(ROOT / "build" / "archive-list.png"))
            page.close()
        b.close()


def test_static_urls_and_sw_cache_are_versioned(tmp_path):
    """S18: 정적 파일 주소 ?v=<해시> 와 서비스 워커 캐시 이름이 같은 해시 — 고정 이름(news-v1)이면 한 번 연 기기가 옛 app.js 를 계속 썼다."""
    from pipeline.render import asset_version

    site = tmp_path / "docs"
    publish(edition(), load_config(), load_interests(), load_sources(), site)
    v = asset_version()
    html = (site / "index.html").read_text(encoding="utf-8")
    sw = (site / "sw.js").read_text(encoding="utf-8")
    assert f'static/app.js?v={v}"' in html and f'static/app.css?v={v}"' in html
    assert f'const VER = "{v}";' in sw and "__VER__" not in sw
    assert len(v) == 10


def test_old_archives_pruned(tmp_path):
    site = tmp_path / "docs"
    (site / "archive" / "2025-01-01").mkdir(parents=True)
    publish(edition(), load_config(), load_interests(), load_sources(), site, keep_days=180)
    assert not (site / "archive" / "2025-01-01").exists()


def test_archives_kept_two_weeks_by_default(tmp_path):
    """기본 보관 14일 (2026-10-30): 호 날짜 2026-10-16 기준 10-02 까지 남고 10-01 은 지운다. 목록에서도 빠진다."""
    site = tmp_path / "docs"
    for d in ("2026-10-01", "2026-10-02"):
        (site / "archive" / d).mkdir(parents=True)
    publish(edition(), load_config(), load_interests(), load_sources(), site)
    listing = (site / "archive" / "index.html").read_text(encoding="utf-8")
    assert not (site / "archive" / "2026-10-01").exists() and (site / "archive" / "2026-10-02").exists()
    assert "2026-10-01" not in listing


def run_verify(site, ed_path):
    return subprocess.run([sys.executable, str(ROOT / "tools" / "verify_site.py"), str(site), str(ed_path)],
                          capture_output=True, text=True, encoding="utf-8")


def test_verify_blocks_plaintext_and_passes_encrypted(tmp_path):
    site = tmp_path / "docs"
    ed = edition()
    ed_path = tmp_path / "ed.json"
    ed_path.write_text(json.dumps(ed, ensure_ascii=False), encoding="utf-8")
    files = publish(ed, load_config(), load_interests(), load_sources(), site)
    r = run_verify(site, ed_path)
    assert r.returncode == 1 and "암호화 안 됨" in r.stdout and "평문" in r.stdout
    for f in files:  # 암호화된 것처럼 바꿔 놓으면 통과
        f.write_text("<html><script>/* staticrypt */ var encrypted='...';</script></html>", encoding="utf-8")
    r = run_verify(site, ed_path)
    assert r.returncode == 0, r.stdout


def test_verify_catches_secret_like_strings(tmp_path):
    site = tmp_path / "docs"
    site.mkdir()
    (site / "x.js").write_text("const t = 'sk-ant-oat01-ABCDEFGHIJKLMNOP';", encoding="utf-8")
    r = run_verify(site, tmp_path / "none.json")
    assert r.returncode == 1 and "비밀값" in r.stdout
