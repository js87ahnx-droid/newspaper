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

from .interest import build_interest_table
from .settings import ROOT, TOPICS, Config, Interests, Sources
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


def _client_config(edition: dict, cfg: Config, interests: Interests, d: date) -> dict:
    """브라우저의 피드백 재계산(feedback.js)이 쓰는 값. 서버 점수 계산(score.py)과 같은 식을 쓰도록 같은 값을 넘긴다."""
    table = build_interest_table(interests)
    w = cfg.weights
    st = edition.get("stats", {})
    return {
        "edition": edition["edition"], "masthead": masthead(d),
        "weights": {"attention": w.attention, "importance": w.importance, "continuity": w.continuity, "interest": w.interest},
        "topicWeights": table.topic_weights, "keywords": list(table.keywords), "keywordBoost": table.keyword_boost,
        "maxInterest": (max(table.topic_weights.values(), default=1) + table.keyword_boost) or 1,
        "interestCap": st.get("interest_cap", 0), "interestCounted": st.get("interest_counted", 0),
        "topics": TOPICS, "topicSection": {"politics": "politics", "economy": "economy", "industry": "economy",
                                           "semis_ai": "economy", "international": "international"},
        "sectionTitles": {s.id: s.title for s in cfg.sections},
        "sectionCaps": {s.id: s.max_articles for s in cfg.sections},
    }


def _opinion_view(op: dict | None) -> dict | None:
    """논평·사설면: 사설 목록은 6편씩 끊어 쪽 나누기가 자연스럽게 되도록."""
    if not op or not (op["compare"] or op["editorials"] or op["columns"]):
        return None
    for g in (g for c in op["compare"] for g in c["groups"]):
        g["cls"] = LEAN_CLASS.get(g["lean"], "mid")
    eds = [{**e, "cls": LEAN_CLASS.get(e["lean"], "mid")} for e in op["editorials"]]
    cols = [{**c, "cls": LEAN_CLASS.get(c["lean"], "mid")} for c in op["columns"]]
    return {"compare": op["compare"], "editorial_chunks": [eds[i:i + 6] for i in range(0, len(eds), 6)], "columns": cols}


def build_context(edition: dict, cfg: Config, interests: Interests, sources: Sources) -> dict:
    d = date.fromisoformat(edition["edition"])
    titles = {s.id: s.title for s in cfg.sections}
    sections = []
    for s in cfg.sections:
        if s.id in ("compare", "guide", "opinion"):
            continue
        items = edition["sections"].get(s.id, [])
        if not items:
            continue
        sections.append({"id": s.id, "title": titles[s.id], "items": [
            {**it, "view": _display(it, interests.foreign_display),
             # 1면 톱·다양성·연속 보장 기사는 피드백으로도 빼지 않는다 (feedback.js)
             "guaranteed": any(r.startswith(("1면 톱", "다양성", "연속")) for r in it.get("reasons", []))}
            for it in items]})
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
        "opinion": _opinion_view(edition.get("opinion")), "opinion_title": titles.get("opinion", "논평·사설"),
        "lean_class": LEAN_CLASS, "stats": edition.get("stats", {}), "lead_max": LEAD_MAX,
        "edition_json": json.dumps(_client_config(edition, cfg, interests, d), ensure_ascii=False).replace("</", "<\\/"),  # 스크립트 안 "</script>" 방지
    }


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html", "j2"]),
                       trim_blocks=True, lstrip_blocks=True)


def render_html(edition: dict, cfg: Config, interests: Interests, sources: Sources, base: str = "") -> str:
    """지면 HTML 한 장. base 는 정적 파일까지의 상대 경로 앞부분 (지난 호 페이지는 "../../")."""
    ctx = build_context(edition, cfg, interests, sources)
    ctx["base"] = base
    client = _client_config(edition, cfg, interests, date.fromisoformat(edition["edition"]))
    client["base"] = base
    ctx["edition_json"] = json.dumps(client, ensure_ascii=False).replace("</", "<\\/")  # 스크립트 안 "</script>" 방지
    return _env().get_template("edition.html.j2").render(**ctx)


def write_assets(site: Path, masthead_name: str) -> None:
    """정적 파일 (CSS·JS·page-flip·아이콘)과 manifest·서비스 워커 — 기사 이미지는 복사하지 않는다."""
    if (site / "static").exists():
        shutil.rmtree(site / "static")
    shutil.copytree(ROOT / "static", site / "static", ignore=shutil.ignore_patterns(".gitkeep"))
    manifest = {
        "name": masthead_name, "short_name": masthead_name, "start_url": "./", "scope": "./",
        "display": "standalone", "orientation": "landscape", "background_color": "#f6f1e7", "theme_color": "#f6f1e7",
        "icons": [{"src": "static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "static/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }
    (site / "manifest.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    shutil.copy(ROOT / "templates" / "sw.js", site / "sw.js")


def render(edition: dict, cfg: Config, interests: Interests, sources: Sources, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render_html(edition, cfg, interests, sources), encoding="utf-8")
    write_assets(out_dir, masthead(date.fromisoformat(edition["edition"])))
    return out_dir / "index.html"


def render_archive_index(dates: list[date], base: str = "../") -> str:
    return _env().get_template("archive.html.j2").render(
        base=base, items=[{"date": d.isoformat(), "name": masthead(d),
                           "long": f"{d.year}년 {d.month}월 {d.day}일 {'월화수목금토일'[d.weekday()]}요일"} for d in dates])
