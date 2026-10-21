"""7단계 발행 준비: GitHub Pages 가 서비스하는 site(docs/) 폴더를 만든다.

docs/index.html                오늘 호
docs/archive/<날짜>/index.html   날짜별 지난 호 (보관 기간이 지나면 지움)
docs/archive/index.html        지난 호 목록
docs/static/ …                 CSS·JS·아이콘 (기사 내용 없음)

HTML 은 이 단계 뒤에 StaticCrypt 로 암호화한다(scripts/daily.sh). 이 함수는 암호화할 파일 목록을 돌려준다.
"""
from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path

from .render import masthead, render_archive_index, render_html, write_assets
from .settings import Config, Interests, Sources


def publish(edition: dict, cfg: Config, interests: Interests, sources: Sources, site: Path, keep_days: int = 180) -> list[Path]:
    d = date.fromisoformat(edition["edition"])
    site.mkdir(parents=True, exist_ok=True)
    write_assets(site, masthead(d))
    (site / ".nojekyll").write_text("", encoding="utf-8")
    today = site / "index.html"
    today.write_text(render_html(edition, cfg, interests, sources, base=""), encoding="utf-8")
    arch = site / "archive" / d.isoformat()
    arch.mkdir(parents=True, exist_ok=True)
    (arch / "index.html").write_text(render_html(edition, cfg, interests, sources, base="../../"), encoding="utf-8")
    # 보관 기간이 지난 호 정리
    cutoff = d - timedelta(days=keep_days)
    dates = []
    for p in (site / "archive").iterdir():
        if not p.is_dir():
            continue
        try:
            pd = date.fromisoformat(p.name)
        except ValueError:
            continue
        if pd < cutoff:
            shutil.rmtree(p)
        else:
            dates.append(pd)
    index = site / "archive" / "index.html"
    index.write_text(render_archive_index(sorted(dates, reverse=True)), encoding="utf-8")
    return [today, arch / "index.html", index]
