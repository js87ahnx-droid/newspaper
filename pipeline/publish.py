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

from .render import VARIANT_LABELS, masthead, render_archive_index, render_html, write_assets
from .settings import Config, Interests, Sources


def publish(edition: dict, cfg: Config, interests: Interests, sources: Sources, site: Path, keep_days: int = 180) -> list[Path]:
    d = date.fromisoformat(edition["edition"])
    site.mkdir(parents=True, exist_ok=True)
    write_assets(site, masthead(d))
    (site / ".nojekyll").write_text("", encoding="utf-8")
    today = site / "index.html"
    arch = site / "archive" / d.isoformat()
    arch.mkdir(parents=True, exist_ok=True)
    variants = list(dict.fromkeys(cfg.layout_variants))
    today.write_text(render_html(edition, cfg, interests, sources, base="",
                                 variant_links=variant_links(variants, "base", f"archive/{d.isoformat()}/")), encoding="utf-8")
    (arch / "index.html").write_text(render_html(edition, cfg, interests, sources, base="../../",
                                                 variant_links=variant_links(variants, "base", "")), encoding="utf-8")
    extra = []
    # 비교용 판 (S26): archive/<날짜>/a/·b/ — 정적 파일은 공유. 오늘 호 위치에는 기존 판만
    for v in variants:
        vd = arch / v
        vd.mkdir(exist_ok=True)
        (vd / "index.html").write_text(render_html(edition, cfg, interests, sources, base="../../../", variant=v,
                                                   variant_links=variant_links(variants, v, "../")), encoding="utf-8")
        extra.append(vd / "index.html")
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
    return [today, arch / "index.html", index, *extra]


def variant_links(variants: list[str], current: str, to_arch: str) -> list[dict]:
    """판 고르기 링크. to_arch: 지금 페이지에서 archive/<날짜>/ 까지의 상대 경로. 비교 판이 없으면 빈 목록."""
    if not variants:
        return []
    return [{"label": VARIANT_LABELS[v], "on": v == current, "href": (to_arch or "./") if v == "base" else f"{to_arch}{v}/"}
            for v in ["base", *variants]]
