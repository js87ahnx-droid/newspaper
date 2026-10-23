"""6단계 지면 생성: edition.json → 정적 HTML (종이 넘김은 브라우저에서).

- 쪽 나누기는 브라우저에서 한다 (기기마다 화면 크기가 달라서). 여기서는 섹션별 기사 흐름만 만든다.
- 기사 본문은 넣지 않는다: 제목, RSS 리드(LEAD_MAX 자 이하), 링크, 이미지 주소(원 주소, 복사 안 함)만.
- 제호·탭 제목·홈 화면 이름은 모두 "○월 ○일자 뉴스".
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import date, datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .interest import build_interest_table
from . import reader as reader_mod
from .settings import ROOT, TOPICS, Config, Interests, Sources
from .stance import LEAN_ORDER
from .textutil import LEAD_MAX, TRANSLATE_BOTH, cap_lead, title_key

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


# 피드가 축소판을 주는 매체 → 같은 사진의 큰 판 주소 (S17c, 2026-10-17 실측: 바꾼 주소가 모두 열림)
_PHOTO_SIZES = [
    (re.compile(r"^(https://ichef\.bbci\.co\.uk/(?:ace|news)/(?:standard|ws)/)\d{2,3}/"), r"\g<1>976/"),            # BBC 240 → 976px
    (re.compile(r"^(https://flexible\.img\.hani\.co\.kr/flexible/normal/)\d+/\d+/"), r"\g<1>970/582/"),         # 한겨레 300 → 970px
    (re.compile(r"^(https://img\.yna\.co\.kr/.+)_P[123](\.\w+)$"), r"\g<1>_P4\g<2>"),                          # 연합 500 → 1183px
]


def larger_photo(url: str | None) -> str | None:
    if not url:
        return url
    for pat, rep in _PHOTO_SIZES:
        new = pat.sub(rep, url)
        if new != url:
            return new
    return url


def _display(item: dict, display) -> dict:
    """언어별 표시: 영어 = 원문 제목 + 한국어 요약(있으면), 그 밖 = 번역 제목(있으면) + 원문 제목."""
    rep = next((a for a in item["articles"] if a["title"] == item["title"]), item["articles"][0])
    llm = item.get("llm", {})
    title, orig, lead, lead_note = item["title"], None, item.get("lead", ""), None
    an = llm.get("analysis")
    if an:  # 본문 기반 이슈 정리 (S14): 한국어 제목 + 요약, 원 제목은 작게
        return {
            "title": an["headline"] or item["title"], "orig_title": item["title"] if an["headline"] else None,
            "lead": an["summary"], "lead_note": "AI 정리", "analysis": an,
            "lang": rep["lang"], "paywall": rep.get("paywall", False), "kind": rep.get("kind", "rss"),
        }
    if rep["lang"] in TRANSLATE_BOTH:   # S20b·S20d: 한국어 제목 + 한국어 요약, 원 제목은 작게
        if llm.get("ko_title"):
            title, orig = llm["ko_title"], item["title"]
        if llm.get("ko_summary"):
            lead, lead_note = llm["ko_summary"], "AI 요약"
    elif rep["lang"] == "en" and display.english == "original_with_ko_summary" and llm.get("ko_summary"):
        lead, lead_note = llm["ko_summary"], "AI 요약"
    elif rep["lang"] not in ("ko", "en") and display.other == "translated_title" and llm.get("ko_title"):
        title, orig, lead_note = llm["ko_title"], item["title"], "AI 번역 제목"
    return {
        "title": title, "orig_title": orig, "lead": cap_lead(lead or ""), "lead_note": lead_note,
        "lang": rep["lang"], "paywall": rep.get("paywall", False), "kind": rep.get("kind", "rss"),
    }


SHORT_NAME = {"조선일보": "조선", "중앙일보": "중앙", "동아일보": "동아", "한겨레": "한겨레", "경향신문": "경향", "한국경제": "한경",
              "매일경제": "매경", "연합뉴스": "연합", "New York Times": "NYT", "Wall Street Journal": "WSJ", "Fox News": "Fox",
              "Global Times": "환구시보", "Al Jazeera": "알자지라", "NHK World": "NHK World",
              "Financial Times": "FT", "Washington Post": "WaPo", "The Economist": "Economist",
              "요미우리신문": "요미우리", "아사히신문": "아사히", "인민일보": "인민", "신화통신": "신화", "Der Spiegel": "Spiegel"}


def headline_label(by: dict) -> str | None:
    """'1면 조선·동아 / 헤드라인 BBC' — 종이신문 1면(naver_a1)과 홈페이지·피드 헤드라인을 나눠 순위 순으로 (S19a: "머리"→"헤드라인")."""
    if not by:
        return None
    order = sorted(by.items(), key=lambda kv: (kv[1][0], kv[0]))
    a1 = [SHORT_NAME.get(n, n) for n, (_, via) in order if via == "naver_a1"]
    top = [SHORT_NAME.get(n, n) for n, (_, via) in order if via != "naver_a1"]
    parts = ([f"1면 {'·'.join(a1)}"] if a1 else []) + ([f"헤드라인 {'·'.join(top)}"] if top else [])
    return " / ".join(parts)


# 매체별 관점에서 LLM 이 쓰는 한글 매체 이름 (S19b 평가: 10/16 "가디언·월스트리트저널·뉴욕타임스"가 안 맞음)
KO_NAMES = {"New York Times": "뉴욕타임스", "Wall Street Journal": "월스트리트저널", "Guardian": "가디언", "Fox News": "폭스뉴스",
            "Reuters": "로이터", "AP": "AP통신", "Nikkei Asia": "닛케이", "Japan Times": "재팬타임스", "SCMP": "사우스차이나모닝포스트",
            "Bloomberg": "블룸버그", "Financial Times": "파이낸셜타임스", "The Economist": "이코노미스트", "Le Monde": "르몽드",
            "Washington Post": "워싱턴포스트", "Al Jazeera": "알자지라", "Global Times": "환구시보", "BBC": "비비씨", "CNN": "씨엔엔",
            "Politico": "폴리티코", "Politico Europe": "폴리티코 유럽", "Der Spiegel": "슈피겔"}


def _source_key(name: str) -> str:
    return re.sub(r"[\s.·'’-]|^the", "", name.casefold())


def stance_links(it: dict, analysis: dict | None) -> list[dict]:
    """매체별 관점 (S19b): 줄마다 그 매체의 이슈 기사(대표 = 첫 기사)를 붙여 원문 창으로. LLM 이 쓴 매체 이름이
    정식 이름·약칭(NYT·WSJ·조선 등)·앞뒤 일부("The Guardian"↔"Guardian")와 맞으면, 맞는 기사가 없으면 article 없음."""
    if not analysis or not analysis.get("stances"):
        return []
    first: dict[str, dict] = {}
    for a in it.get("articles", []):
        for k in {_source_key(n) for n in (a["source"], SHORT_NAME.get(a["source"], ""), KO_NAMES.get(a["source"], "")) if n}:
            first.setdefault(k, a)
    out = []
    for st in analysis["stances"]:
        k = _source_key(st.get("source", ""))
        art = first.get(k) or (next((a for kk, a in first.items() if len(k) >= 3 and (k in kk or kk in k)), None) if k else None)
        out.append({**st, "article": art})
    return out


def _client_config(edition: dict, cfg: Config, interests: Interests, d: date) -> dict:
    """브라우저의 피드백 재계산(feedback.js)이 쓰는 값. 서버 점수 계산(score.py)과 같은 식을 쓰도록 같은 값을 넘긴다."""
    table = build_interest_table(interests)
    w = cfg.weights
    st = edition.get("stats", {})
    return {
        "edition": edition["edition"], "masthead": masthead(d),
        "weights": {"attention": w.attention, "importance": w.importance, "continuity": w.continuity, "interest": w.interest,
                    "headline": w.headline},
        "topicWeights": table.topic_weights, "keywords": list(table.keywords), "keywordBoost": table.keyword_boost,
        "maxInterest": (max(table.topic_weights.values(), default=1) + table.keyword_boost) or 1,
        "interestCap": st.get("interest_cap", 0), "interestCounted": st.get("interest_counted", 0),
        # 단신 분야 묶음 순서 (S19c): 분야 중요도 순, 같으면 TOPICS 순
        "briefTopics": sorted(TOPICS, key=lambda k: -cfg.importance.topic_weights.get(k, 0)),
        "topics": TOPICS, "topicSection": {"politics": "politics", "economy": "economy", "industry": "economy",
                                           "semis_ai": "economy", "international": "international",
                                           "society": "society", "science": "society"},
        "sectionTitles": {s.id: s.title for s in cfg.sections},
        "sectionCaps": {s.id: s.max_articles for s in cfg.sections},
        "sectionPages": {s.id: s.pages for s in cfg.sections},
    }


NEWS_SECTIONS = ("front", "politics", "economy", "international", "society", "interest")


def lead_story(cands: list[dict], country: dict[str, str]) -> dict:
    """1면 메인 기사 (S26, 사용자 2026-10-21: "신문을 보는 사람이 알아야 할 가장 중요한 기사. 한국 뉴스 우선,
    전세계가 주목하는 해외 이슈가 있으면 그것").
    - 전세계 주목 = 한국 매체 기사가 절반 미만이고, 해외 매체 3곳 이상이 홈페이지·피드 헤드라인으로 올리고 4개국 이상 보도,
      또는 6개국 이상 보도 → 해외 헤드라인 수·주목도 순
    - 없으면 한국 기사(한국 매체 기사가 절반 이상) 중 그날 한국 신문 1면에 가장 많이 오른 것 → 1면 후보 → 주목도
    - 둘 다 없으면 1면 1위"""
    def kr_share(it):
        arts = it.get("articles") or []
        return sum(country.get(a.get("source")) == "KR" for a in arts) / max(1, len(arts))

    heads = lambda it: (it.get("headline_by") or {}).items()
    a1 = lambda it: sum(1 for _, v in heads(it) if v[1] == "naver_a1")
    foreign = lambda it: sum(1 for n, v in heads(it) if v[1] != "naver_a1" and country.get(n) != "KR")
    countries = lambda it: (it.get("coverage") or {}).get("countries", 0)
    att = lambda it: (it.get("scores") or {}).get("attention", 0)

    glob = [it for it in cands if kr_share(it) < 0.5 and ((foreign(it) >= 3 and countries(it) >= 4) or countries(it) >= 6)]
    if glob:
        return max(glob, key=lambda it: (foreign(it), att(it)))
    kr = [it for it in cands if kr_share(it) >= 0.5]
    if kr:
        return max(kr, key=lambda it: (a1(it), it.get("_front", False), att(it)))
    return cands[0]


def front_single(sections: list[dict], country: dict[str, str]) -> None:
    """1면 첫 쪽 (S26): 메인 기사 1건만, 사진과 함께 — 좌우로 나누지 않는다. 나머지 1면 기사는 1면 둘째 쪽에 그대로.
    메인 기사의 각도별 묶음(요약·배경·쟁점·관점·입장 차이·관련·사설)은 지면에 다시 싣지 않고 "자세히 보기"(자세히 창)로만.
    메인 기사에 사진이 없으면(사진 자리가 아닌 다른 면 기사) 그 이슈 기사들의 RSS 대표 이미지(photo_alt — 발행 때 채움)."""
    front = next((s for s in sections if s["id"] == "front"), None)
    if not front or not front["items"]:
        return
    for r in front["items"]:
        r["_front"] = True
    cands = [r for s in sections if s["id"] in NEWS_SECTIONS for r in s["items"] if not r.get("reserve")]
    lead = lead_story(cands, country)
    for s in sections:   # 다른 면에 있던 기사가 메인이 되면 그 면에서 뺀다
        if s["id"] != "front":
            s["items"] = [r for r in s["items"] if r is not lead]
    if not lead.get("photo") and lead.get("photo_alt"):
        lead["photo"], lead["photo_source"] = larger_photo(lead["photo_alt"]), lead.get("photo_alt_source")
    front["items"] = [r for r in front["items"] if r is not lead]
    an = lead["view"].get("analysis") or {}
    lead["sub"] = an.get("brief") if an.get("brief") and an.get("brief") != lead["view"]["title"] else None
    front["lead"] = lead
    # 자세히 창이 쓰는 원본 — 쪽 나누기에는 들어가지 않는다 (템플릿이 숨은 칸으로 쓴다)
    sections.append({"id": "detail", "title": "", "items": [{**lead, "detail": True}]})


def _opinion_view(op: dict | None) -> dict | None:
    """논평·사설면: 사설·칼럼 목록은 6편·5편씩 끊어 쪽 나누기가 자연스럽게 되도록 (칼럼 한 덩어리가 통째로 다음 쪽으로 넘어가 앞 쪽이 비던 것 — S18)."""
    if not op or not (op["compare"] or op["editorials"] or op["columns"]):
        return None
    for g in (g for c in op["compare"] for g in c["groups"]):
        g["cls"] = LEAN_CLASS.get(g["lean"], "mid")
    eds = [{**e, "cls": LEAN_CLASS.get(e["lean"], "mid")} for e in op["editorials"]]
    cols = [{**c, "cls": LEAN_CLASS.get(c["lean"], "mid")} for c in op["columns"]]
    return {"compare": op["compare"], "editorial_chunks": [eds[i:i + 6] for i in range(0, len(eds), 6)],
            "columns": cols, "column_chunks": [cols[i:i + 5] for i in range(0, len(cols), 5)]}


def time_label(published: str | None, tz: str) -> str | None:
    """기사 시각 → "10/16 05:12" (호의 시간대)."""
    if not published:
        return None
    try:
        t = datetime.fromisoformat(published).astimezone(ZoneInfo(tz))
    except ValueError:
        return None
    return f"{t.month}/{t.day} {t:%H:%M}"


def brief_text(it: dict, view: dict) -> str:
    """단신 한 줄: LLM 한 줄 정리 → 리드 첫 문장(제목을 되풀이하지 않을 때). 없으면 빈 문자열."""
    an = view.get("analysis")
    if an and an.get("brief"):
        return an["brief"]
    lead = (view.get("lead") or "").strip()
    first = re.split(r"(?<=[.!?。])\s|(?<=다\.)\s", lead, maxsplit=1)[0] if lead else ""
    return first[:90] if first and not title_key(first).startswith(title_key(it["title"])[:15]) else ""


def _lean_groups(it: dict) -> list[dict]:
    st = it.get("stance", {})
    lw = st.get("lean_words", {})
    return [{"group": g["group"], "cls": LEAN_CLASS.get(g["group"], "mid"),
             "articles": [{**a, "title_html": _highlight(a["title"], lw.get(g["group"], []))} for a in g["articles"]]}
            for g in st.get("lean", [])]


def related_opinions(op: dict | None) -> dict[str, list[dict]]:
    """논평면에서 지면 이슈와 연결한 사설·칼럼(관련: …)을 이슈별로 (S17e — 기사 곁에 보인다). 사설이 칼럼보다 먼저."""
    if not op:
        return {}
    out: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for o in sorted(op.get("editorials", []) + op.get("columns", []), key=lambda o: o.get("kind") != "editorial"):
        if not o.get("issue_id") or o["url"] in seen:
            continue
        seen.add(o["url"])
        out.setdefault(o["issue_id"], []).append({**o, "cls": LEAN_CLASS.get(o.get("lean"), "mid")})
    return out


def build_context(edition: dict, cfg: Config, interests: Interests, sources: Sources) -> dict:
    d = date.fromisoformat(edition["edition"])
    titles = {s.id: s.title for s in cfg.sections}
    compare_ids = {it["issue_id"] for it in edition.get("compare", [])}
    rel_ops = related_opinions(edition.get("opinion"))
    sections = []
    for s in cfg.sections:
        if s.id in ("compare", "guide", "opinion"):
            continue
        if s.id == "analysis":   # 매체가 쓴 분석·해설 (S22c) — 이슈 기사가 아니라 따로 모은 목록
            an = [{**a, "cls": LEAN_CLASS.get(a.get("lean"), "mid"), "time": time_label(a.get("published"), cfg.timezone)}
                  for a in (edition.get("analysis") or [])[:10]]   # AI 가 걸러 내지 못했을 때(LLM 꺼짐)도 10편까지
            # 인터뷰 (S27): AI 가 고른 석학·사상가·구루·지도자 인터뷰 — 분석과 겹치는 주소는 인터뷰로만
            iv = [{**a, "cls": LEAN_CLASS.get(a.get("lean"), "mid"), "time": time_label(a.get("published"), cfg.timezone)}
                  for a in (edition.get("interviews") or [])]
            an = [a for a in an if a["url"] not in {i["url"] for i in iv}]
            if an or iv:
                sections.append({"id": "analysis", "title": titles[s.id], "items": [], "analysis": an, "interviews": iv})
            continue
        items = edition["sections"].get(s.id, [])
        if not items:
            continue
        rows = []
        for it in items:
            view = _display(it, interests.foreign_display)
            rep = next((a for a in it["articles"] if a.get("url") == it.get("url")), it["articles"][0])
            rows.append({
                **it, "view": view, "photo": larger_photo(it.get("photo")), "headline_label": headline_label(it.get("headline_by", {})),
                "time": time_label(rep.get("published"), cfg.timezone),
                # 흐름 (S29b): 오늘 앞선 보도(지난 소식으로 빠졌거나 같은 묶음의 앞선 시점) → 지금 이 기사
                "updates_view": [{**u, "time": time_label(u.get("published"), cfg.timezone)} for u in it.get("updates", [])],
                "brief_text": brief_text(it, view),
                "stance_links": stance_links(it, view.get("analysis")),
                # 관련 기사 (S22b): 단신에서 옮겨 온 이어진 기사 — 제목(외국어는 번역 제목) → 원문 창
                "related_view": [{**r, "view": _display(r, interests.foreign_display), "cls": LEAN_CLASS.get(r["lean"], "mid"),
                                  "rep": next((a for a in r["articles"] if a.get("url") == r.get("url")), r["articles"][0])}
                                 for r in it.get("related", [])],
                # 입장 차이: 따로 면을 두지 않고 대표 기사 바로 아래에 (S15, 요청 2)
                "cmp_groups": _lean_groups(it) if it["issue_id"] in compare_ids and len(it.get("stance", {}).get("lean", [])) >= 2 else [],
                # 1면 톱·다양성·연속 보장 기사는 피드백으로도 빼지 않는다 (feedback.js)
                "guaranteed": any(r.startswith(("1면 톱", "다양성", "연속")) for r in it.get("reasons", [])),
                # 관련 사설·칼럼 (S17e): 같은 사건으로 합쳐진 이슈에 연결된 것도
                "opinions": [o for iid in [it["issue_id"], *it.get("merged", [])] for o in rel_ops.get(iid, [])],
            })
        sections.append({"id": s.id, "title": titles[s.id], "items": rows})
    front_single(sections, {s.name: s.country for s in sources.sources})
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
        # 지정 칼럼 (S22d): 논평면 맨 앞 칸
        "picks": [{**p, "cls": LEAN_CLASS.get(p.get("lean"), "mid"), "time": time_label(p.get("published"), cfg.timezone)}
                  for p in edition.get("picks") or []],
        "lean_class": LEAN_CLASS, "stats": edition.get("stats", {}), "lead_max": LEAD_MAX,
        "edition_json": json.dumps(_client_config(edition, cfg, interests, d), ensure_ascii=False).replace("</", "<\\/"),  # 스크립트 안 "</script>" 방지
    }


def asset_version() -> str:
    """정적 파일 내용의 짧은 해시. 지면의 CSS·JS 주소 뒤 ?v= 와 서비스 워커 캐시 이름에 쓴다 —
    캐시 이름이 고정(news-v1)이고 정적 파일을 캐시 먼저 내주어, 한 번 연 기기는 새 app.js 를 받지 못했다 (S18)."""
    h = hashlib.sha1()
    for f in sorted(p for p in (ROOT / "static").rglob("*") if p.is_file()):
        h.update(f.relative_to(ROOT).as_posix().encode())
        h.update(f.read_bytes())
    h.update((ROOT / "templates" / "sw.js").read_bytes())
    return h.hexdigest()[:10]


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.globals["ver"] = asset_version()
    return env


def render_html(edition: dict, cfg: Config, interests: Interests, sources: Sources, base: str = "") -> str:
    """지면 HTML 한 장. base 는 정적 파일까지의 상대 경로 앞부분 (지난 호 페이지는 "../../")."""
    ctx = build_context(edition, cfg, interests, sources)
    ctx["base"] = base
    client = _client_config(edition, cfg, interests, date.fromisoformat(edition["edition"]))
    client["base"] = base
    # 원문 재배열 보기 (S17): 중계 서버가 설정됐을 때만. 키는 이 HTML(암호화됨) 안에만 들어간다
    rc = reader_mod.config()
    client["reader"] = rc
    ctx["read_url"] = reader_mod.read_url_fn(edition, sources) if rc else (lambda url, source=None: "")
    real = edition.get("read_urls", {})   # Google 뉴스 경유 주소 → 발행 때 푼 실제 기사 주소 ("링크"가 바로 가게)
    ctx["real_url"] = lambda url: real.get(url, url)
    ctx["edition_json"] = json.dumps(client, ensure_ascii=False).replace("</", "<\\/")  # 스크립트 안 "</script>" 방지
    return _env().get_template("edition.html.j2").render(**ctx)


def write_assets(site: Path, masthead_name: str) -> None:
    """정적 파일 (CSS·JS·아이콘)과 manifest·서비스 워커 — 기사 이미지는 복사하지 않는다."""
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
    sw = (ROOT / "templates" / "sw.js").read_text(encoding="utf-8").replace("__VER__", asset_version())
    (site / "sw.js").write_text(sw, encoding="utf-8")


def render(edition: dict, cfg: Config, interests: Interests, sources: Sources, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render_html(edition, cfg, interests, sources), encoding="utf-8")
    write_assets(out_dir, masthead(date.fromisoformat(edition["edition"])))
    return out_dir / "index.html"


def render_archive_index(dates: list[date], base: str = "../") -> str:
    return _env().get_template("archive.html.j2").render(
        base=base, items=[{"date": d.isoformat(), "name": masthead(d),
                           "long": f"{d.year}년 {d.month}월 {d.day}일 {'월화수목금토일'[d.weekday()]}요일"} for d in dates])
