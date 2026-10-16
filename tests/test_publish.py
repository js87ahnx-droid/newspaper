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
    assert 'href="../../static/app.css"' in arch and '"base": "../../"' in arch
    listing = (site / "archive" / "index.html").read_text(encoding="utf-8")
    assert listing.index("10월 16일자 뉴스") < listing.index("10월 15일자 뉴스")  # 최신이 위


def test_old_archives_pruned(tmp_path):
    site = tmp_path / "docs"
    (site / "archive" / "2025-01-01").mkdir(parents=True)
    publish(edition(), load_config(), load_interests(), load_sources(), site, keep_days=180)
    assert not (site / "archive" / "2025-01-01").exists()


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
