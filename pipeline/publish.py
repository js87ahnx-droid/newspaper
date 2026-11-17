"""7단계 발행 준비: GitHub Pages 가 서비스하는 site(docs/) 폴더를 만든다.

docs/index.html                오늘 호
docs/archive/<날짜>/index.html   날짜별 지난 호 (보관 기간이 지나면 지움)
docs/archive/index.html        지난 호 목록
docs/static/ …                 CSS·JS·아이콘 (기사 내용 없음)

HTML 은 이 단계 뒤에 StaticCrypt 로 암호화한다(scripts/daily.sh). 이 함수는 암호화할 파일 목록을 돌려준다.
"""
from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

from .fsutil import write_atomic
from .render import lead_record, masthead, render_archive_index, render_html, write_assets
from .settings import Config, Interests, Sources


#: 옛 b/ 주소 → 한 단계 위 (S53). 문구만 있고 기사 내용 없음
REDIRECT = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="robots" content="noindex, nofollow">
<meta http-equiv="refresh" content="0; url=../"><title>일자 뉴스</title></head>
<body><p>지면 주소가 바뀌었습니다. <a href="../">지면으로 가기</a></p>
<script>location.replace("../" + location.hash);</script></body></html>
"""

#: 지난 호 보관 일수 (2026-10-30 사용자 "2주까지만") — 지면만. 연속성 기록(data/history)은 따로 두고 지우지 않는다
ARCHIVE_KEEP_DAYS = 14


def _read_history(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _archive_highlights(history_dir: Path | None, d: date, lead: dict | None, dates: list[date]) -> dict[str, str]:
    """이 호의 1면 메인 제목과 판정 기록을 연속성 기록에 남기고, 목록에 실을 호들의 제목을 읽는다.
    docs 는 평문 제목을 두면 안 되므로(tools/verify_site.py) 제목을 이미 저장하는 data/history 에 둔다."""
    if history_dir is None:
        return {}
    path = history_dir / f"{d.isoformat()}.json"
    data = _read_history(path)
    if data is not None and lead:
        data["lead_title"], data["lead_note"] = lead["title"], lead["note"]
        write_atomic(path, json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    out = {}
    for x in dates:
        t = (_read_history(history_dir / f"{x.isoformat()}.json") or {}).get("lead_title")
        if t:
            out[x.isoformat()] = t
    return out


def publish(edition: dict, cfg: Config, interests: Interests, sources: Sources, site: Path,
            keep_days: int = ARCHIVE_KEEP_DAYS, history_dir: Path | None = None) -> list[Path]:
    d = date.fromisoformat(edition["edition"])
    site.mkdir(parents=True, exist_ok=True)
    write_assets(site, masthead(d))
    write_atomic(site / ".nojekyll", "", encoding="utf-8")
    # S53: 큐레이션 판이 켜져 있으면 그것 하나만 (S50 의 두 판 나란히 발행은 없앰). 꺼지면 기존 판 하나
    variant = "b" if cfg.curated.enabled else None
    today = site / "index.html"
    write_atomic(today, render_html(edition, cfg, interests, sources, base="", variant=variant), encoding="utf-8")
    arch = site / "archive" / d.isoformat()
    arch.mkdir(parents=True, exist_ok=True)
    write_atomic(arch / "index.html", render_html(edition, cfg, interests, sources, base="../../", variant=variant), encoding="utf-8")
    # S50 때의 b 판 주소(오늘 b/·이 호 보관본 b/)는 같은 호 지면으로 넘기는 짧은 페이지로 바꾼다 — b/ 북마크·11/17 큐레이션 판의
    # "오늘" 단추가 404 가 되지 않게 (S53 계획 리뷰 M1). HTML 이라 함께 암호화한다. 지난 날짜 보관본의 b/ 는 그대로 둔다
    moved = []
    for page in (site / "b" / "index.html", arch / "b" / "index.html"):
        if page.parent.is_dir():
            write_atomic(page, REDIRECT, encoding="utf-8")
            moved.append(page)
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
    highlights = _archive_highlights(history_dir, d, lead_record(edition, cfg, interests, sources), dates)
    write_atomic(index, render_archive_index(sorted(dates, reverse=True), highlights=highlights), encoding="utf-8")
    return [today, arch / "index.html", index, *moved]
