"""6단계 지면 생성: edition.json → 정적 HTML (종이 넘김은 브라우저에서).

- 쪽 나누기는 브라우저에서 한다 (기기마다 화면 크기가 달라서). 여기서는 섹션별 기사 흐름만 만든다.
- 기사 본문은 넣지 않는다: 제목, RSS 리드(LEAD_MAX 자 이하), 링크, 이미지 주소(원 주소, 복사 안 함)만.
- 제호·탭 제목·홈 화면 이름은 모두 "○월 ○일자 뉴스".
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import date
from html import escape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .settings import ROOT, Config, Interests, Sources
from .stance import LEAN_ORDER
from .textutil import LEAD_MAX, cap_lead

LEAN_CLASS = {"보수": "con", "중도": "mid", "진보": "pro", "경제지": "biz", "통신·공영": "pub", "관영": "state"}
KIND_NOTE = {"google_news": "Google 뉴스 경유 (리드 없음)"}


def masthead(d: date) -> str:
    return f"{d.month}월 {d.day}일자 뉴스"


def _highlight(text: str, words: list[str]) -> Markup:
    """특징 단어에 <mark> (대소문자 무시). 입력은 먼저 이스케이프한다."""
    out = escape(text)
    for w in sorted(set(words), key=len, reverse=True):
        if len(w) < 2:
            continue
        out = re.sub(re.escape(escape(w)), lambda m: f"<mark>{m.group(0)}</mark>", out, flags=re.I)
    return Markup(out)


def _display(item: dict, display) -> dict:
    """언어별 표시: 영어 = 원문 제목 + 한국어 요약(있으면), 그 밖 = 번역 제목(있으면) + 원문 제목."""
    rep = next((a for a in item["articles"] if a["title"] == item["title"]), item["articles"][0])
    llm = item.get("llm", {})
    title, orig, lead, lead_note = item["title"], None, item.get("lead", ""), None
    if rep["lang"] == "en" and display.english == "original_with_ko_summary" and llm.get("ko_summary"):
        lead, lead_note = llm["ko_summary"], "AI 요약"
    elif rep["lang"] not in ("ko", "en") and display.other == "translated_title" and llm.get("ko_title"):
        title, orig, lead_note = llm["ko_title"], item["title"], "AI 번역 제목"
    return {
        "title": title, "orig_title": orig, "lead": cap_lead(lead or ""), "lead_note": lead_note,
        "lang": rep["lang"], "paywall": rep.get("paywall", False), "kind": rep.get("kind", "rss"),
    }


def build_context(edition: dict, cfg: Config, interests: Interests, sources: Sources) -> dict:
    d = date.fromisoformat(edition["edition"])
    titles = {s.id: s.title for s in cfg.sections}
    sections = []
    for s in cfg.sections:
        if s.id in ("compare", "guide"):
            continue
        items = edition["sections"].get(s.id, [])
        if not items:
            continue
        sections.append({"id": s.id, "title": titles[s.id], "items": [{**it, "view": _display(it, interests.foreign_display)} for it in items]})
    compare = []
    for it in edition.get("compare", []):
        st = it.get("stance", {})
        lw, cw = st.get("lean_words", {}), st.get("country_words", {})
        compare.append({
            **it, "view": _display(it, interests.foreign_display),
            "lean_groups": [
                {"group": g["group"], "cls": LEAN_CLASS.get(g["group"], "mid"), "words": lw.get(g["group"], []),
                 "articles": [{**a, "title_html": _highlight(a["title"], lw.get(g["group"], []))} for a in g["articles"]]}
                for g in st.get("lean", [])
            ],
            "country_groups": [
                {"group": g["group"], "words": cw.get(g["group"], []),
                 "articles": [{**a, "title_html": _highlight(a["title"], cw.get(g["group"], []))} for a in g["articles"]]}
                for g in st.get("country", [])
            ],
            "frame_summary": it.get("llm", {}).get("frame_summary"),
        })
    guide = sorted(
        ({"name": s.name, "country": s.country, "lean": s.lean, "cls": LEAN_CLASS.get(s.lean, "mid"), "type": s.type,
          "via": KIND_NOTE.get(s.feeds[0].kind, "공식 RSS") if s.feeds else "", "paywall": s.paywall}
         for s in sources.sources if s.enabled),
        key=lambda x: (x["country"] != "KR", LEAN_ORDER.index(x["lean"]) if x["lean"] in LEAN_ORDER else 9, x["name"]),
    )
    return {
        "masthead": masthead(d), "edition": edition["edition"],
        "date_long": f"{d.year}년 {d.month}월 {d.day}일 {'월화수목금토일'[d.weekday()]}요일",
        "sections": sections, "compare": compare, "compare_title": titles.get("compare", "입장 비교"),
        "guide": guide, "guide_title": titles.get("guide", "매체 성향 가이드·출처"),
        "lean_class": LEAN_CLASS, "stats": edition.get("stats", {}), "lead_max": LEAD_MAX,
        "edition_json": json.dumps({"edition": edition["edition"], "masthead": masthead(d)}, ensure_ascii=False),
    }


def render(edition: dict, cfg: Config, interests: Interests, sources: Sources, out_dir: Path) -> Path:
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    ctx = build_context(edition, cfg, interests, sources)
    out_dir.mkdir(parents=True, exist_ok=True)
    html = env.get_template("edition.html.j2").render(**ctx)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    # 정적 파일 (CSS·JS·page-flip·아이콘) — 이미지는 복사하지 않는다
    if (out_dir / "static").exists():
        shutil.rmtree(out_dir / "static")
    shutil.copytree(ROOT / "static", out_dir / "static", ignore=shutil.ignore_patterns(".gitkeep"))
    manifest = {
        "name": ctx["masthead"], "short_name": ctx["masthead"], "start_url": "./", "scope": "./",
        "display": "standalone", "orientation": "landscape", "background_color": "#f6f1e7", "theme_color": "#f6f1e7",
        "icons": [{"src": "static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "static/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }
    (out_dir / "manifest.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    shutil.copy(ROOT / "templates" / "sw.js", out_dir / "sw.js")
    return out_dir / "index.html"
