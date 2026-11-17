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

from .fsutil import read_json, write_atomic
from .interest import build_interest_table
from . import reader as reader_mod
from .settings import ROOT, TOPICS, Config, Interests, Sources
from .stance import COUNTRY_LABEL, LEAN_ORDER

COUNTRY_KO = {**COUNTRY_LABEL, "FR": "프랑스", "DE": "독일", "BE": "벨기에"}   # 중국은 지금 비교표 (S37)
from .textutil import LEAD_MAX, TRANSLATE_BOTH, cap_lead, title_key, trim_lead

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


DECK_MAX = 40   # 부제 한 줄 (S49) — 넘으면 버린다


def want_title(lang: str, display) -> bool:
    """한국어 제목을 받아 보일 언어인가 (S49 — llm 한국어 패스와 같은 규칙)."""
    if lang == "ko":
        return False
    mode = display.english if lang == "en" else display.other
    return lang in TRANSLATE_BOTH or mode in ("translated_title", "ko_title_and_summary")


def want_summary(lang: str, display) -> bool:
    if lang == "ko":
        return False
    mode = display.english if lang == "en" else display.other
    return lang in TRANSLATE_BOTH or mode in ("original_with_ko_summary", "ko_title_and_summary")


def deck_of(llm: dict, title: str) -> str | None:
    """부제 한 줄 (S49): 40자 넘거나 제목과 같으면 버린다."""
    d = (llm.get("deck") or "").strip()
    return d if d and len(d) <= DECK_MAX and title_key(d) != title_key(title) else None


def _display(item: dict, display) -> dict:
    """언어별 표시 (S49): 한국어 제목이 있으면 제목 = 한국어·원제목은 작게, 한국어 요약이 있으면 리드 = 요약(AI 요약).
    없으면 원문 그대로. 피드 리드가 문장 중간에서 끝나면 마지막 완결 문장까지 (자세히 창에서 끊기지 않게)."""
    rep = next((a for a in item["articles"] if a["title"] == item["title"]), item["articles"][0])
    llm = item.get("llm", {})
    title, orig, lead, lead_note = item["title"], None, item.get("lead", ""), None
    an = llm.get("analysis")
    if an:  # 본문 기반 이슈 정리 (S14): 한국어 제목 + 요약, 원 제목은 작게
        t = an["headline"] or item["title"]
        return {
            "title": t, "orig_title": item["title"] if an["headline"] else None,
            "lead": an["summary"], "lead_note": "AI 정리", "analysis": an, "deck": deck_of(llm, t),
            "lang": rep["lang"], "paywall": rep.get("paywall", False), "kind": rep.get("kind", "rss"),
        }
    if llm.get("ko_title") and want_title(rep["lang"], display):
        title, orig = llm["ko_title"], item["title"]
    if llm.get("ko_summary"):   # 외국어 요약, 또는 잘린 국내 리드 대신 받은 요약 (S49)
        lead, lead_note = llm["ko_summary"], "AI 요약"
    elif orig:
        lead_note = "AI 번역 제목"
    return {
        # AI 요약은 자르지 않는다 (S48: 지면은 CSS 로 줄여 보이고, 자세히 창은 전체) — 피드 리드만 상한·완결 문장까지(S49)
        "title": title, "orig_title": orig, "lead": (lead or "") if lead_note == "AI 요약" else trim_lead(cap_lead(lead or "")),
        "lead_note": lead_note, "deck": deck_of(llm, title),
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
        # 설정 창 (S30c): "기본값으로" = interests.yaml 만의 값, 마지막 서버 반영 주
        "defaultTopicWeights": interests.base_weights or table.topic_weights, "learnedWeek": interests.learned_week,
        "defaultKeywords": interests.base_keywords if interests.base_keywords is not None else list(table.keywords),
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


LEAD_GLOBAL_BONUS = 3.0   # 전세계 주목 이슈가 한국에서도 크게 다뤄질 때 주는 가점 (신문 1면 한 곳 = 2점)
LEAD_TOP_WEIGHT = 2.0     # 신문 1면 맨 위 기사에 더 주는 점수 (2026-11-06 시험: 1면에 실린 것과 톱을 구분해야 신문 톱과 맞았다)
LEAD_PAGE_WEIGHT = 0.5    # S47 지면 비중: 1면에는 없지만 A2~A6면에 실은 신문마다 (6곳까지)


def lead_signals(it: dict, country: dict[str, str]) -> dict:
    """메인 기사 판정 재료. korea = 한국 언론의 주목도: 신문 1면 2점(맨 위 기사면 2점 더), 그 밖의 한국 매체 머리기사 1점, 보도 매체 0.5점(6곳까지),
    1면 밖 A2~A6면에 실은 신문 0.5점(6곳까지, S47)."""
    heads = (it.get("headline_by") or {}).items()
    a1_top = sum(1 for _, v in heads if v[1] == "naver_a1" and v[0] == 1)
    arts = it.get("articles") or []
    a1 = sum(1 for _, v in heads if v[1] == "naver_a1")
    kr_heads = sum(1 for n, v in heads if v[1] != "naver_a1" and country.get(n) == "KR")
    kr_cov = len({a.get("source") for a in arts if country.get(a.get("source")) == "KR"})
    pages_n = len(it.get("pages_by") or {})
    return {"a1": a1, "a1_top": a1_top, "kr_heads": kr_heads, "kr_cov": kr_cov, "pages_n": pages_n,
            "foreign": sum(1 for n, v in heads if v[1] != "naver_a1" and country.get(n) != "KR"),
            "countries": (it.get("coverage") or {}).get("countries", 0),
            "kr_share": sum(country.get(a.get("source")) == "KR" for a in arts) / max(1, len(arts)),
            "attention": (it.get("scores") or {}).get("attention", 0),
            "korea": 2 * a1 + LEAD_TOP_WEIGHT * a1_top + kr_heads + 0.5 * min(kr_cov, 6) + LEAD_PAGE_WEIGHT * min(pages_n, 6)}


def lead_pick(cands: list[dict], country: dict[str, str]) -> tuple[dict, str]:
    """1면 메인 기사와 고른 까닭 (사용자 2026-11-06: 한국 최대 이슈와 전세계 주목 이슈를 견주되, 전세계 이슈는 한국 언론도 크게 다룰 때만 가점).
    - 전세계 주목 = 해외 매체 3곳 이상이 머리기사로 올리고 4개국 이상 보도, 또는 6개국 이상 보도
    - 한국에서도 큼 = 신문 1면에 오름, 한국 매체 머리기사 2곳 이상, 또는 한국 매체 4곳 이상 보도
    - 한국에서도 큰 전세계 이슈 중 해외 머리기사가 가장 많은 것에 가점을 주어 한국 최대 이슈와 견준다
    - 그런 이슈가 없으면 한국 최대 이슈. 한국 기사가 하나도 없으면 전세계 이슈, 그것도 없으면 1면 1위"""
    sig = {id(it): lead_signals(it, country) for it in cands}
    s = lambda it: sig[id(it)]
    is_global = lambda it: (s(it)["foreign"] >= 3 and s(it)["countries"] >= 4) or s(it)["countries"] >= 6
    big_here = lambda it: s(it)["a1"] >= 1 or s(it)["kr_heads"] >= 2 or s(it)["kr_cov"] >= 4
    glob = [it for it in cands if is_global(it)]
    kr = [it for it in cands if s(it)["kr_share"] >= 0.5]
    top_kr = max(kr, key=lambda it: (s(it)["korea"], it.get("_front", False), s(it)["attention"])) if kr else None
    shared = [it for it in glob if big_here(it)]
    if shared:
        top_g = max(shared, key=lambda it: (s(it)["foreign"], s(it)["korea"], s(it)["attention"]))
        if top_kr is None or s(top_g)["korea"] + LEAD_GLOBAL_BONUS >= s(top_kr)["korea"]:
            return top_g, "전세계+한국"
        return top_kr, "한국 우세"
    if top_kr is not None:
        return top_kr, "한국 이슈"
    if glob:
        return max(glob, key=lambda it: (s(it)["foreign"], s(it)["attention"])), "전세계(한국 기사 없음)"
    return cands[0], "1면 1위"


def lead_story(cands: list[dict], country: dict[str, str]) -> dict:
    return lead_pick(cands, country)[0]


def _lead_note(lead: dict, why: str, cands: list[dict], country: dict[str, str]) -> dict:
    """판정 기록: 고른 까닭·점수와, 그날 신문 1면 톱에 가장 많이 오른 기사. 평소 주간에도 규칙이 맞는지 나중에 견주는 재료."""
    sig = lead_signals(lead, country)
    note = {"why": why, "signals": {k: round(v, 2) for k, v in sig.items()}, "a1_leader": None}
    leader = max(cands, key=lambda it: lead_signals(it, country)["a1_top"])
    tops = lead_signals(leader, country)["a1_top"]
    if tops:
        note["a1_leader"] = {"title": leader["view"]["title"], "tops": tops}
    return note


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
    lead, why = lead_pick(cands, country)
    front["lead_note"] = _lead_note(lead, why, cands, country)
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


def jonghap_hosts(ordered: list[tuple[str, list[dict]]], country: dict[str, str]) -> tuple[dict | None, dict | None, str]:
    """종합면 묶음의 중심 기사 (S49 — render·enrich 가 같은 함수로 같은 답을 낸다).
    ordered: (면 id, 기사들) — 설정의 면 순서. 메인 = lead_pick(뉴스 면, 예비 제외, 1면 기사 _front).
    둘째 이슈 = 1면 기사(1면 순서, 메인 제외) 중 처음으로 ① 종합면 후보 2건 이상 ② 메인의 후보·합친 이슈와 겹치지 않음
    ③ 제목이 메인과 거의 같지 않음(자카드 0.5 미만). 돌려주는 값: (메인, 둘째 또는 None, 메인 고른 까닭)."""
    from .headlines import _jac

    for sid, ps in ordered:
        if sid == "front":
            for r in ps:
                r["_front"] = True
    cands = [r for sid, ps in ordered if sid in NEWS_SECTIONS for r in ps if not r.get("reserve")]
    if not cands:
        return None, None, ""
    lead, why = lead_pick(cands, country)
    taken = {lead["issue_id"], *lead.get("merged", []), *(a["issue_id"] for a in lead.get("angles") or [])}
    second = None
    for r in next((ps for sid, ps in ordered if sid == "front"), []):
        if r is lead or r.get("reserve"):
            continue
        mine = {r["issue_id"], *r.get("merged", []), *(a["issue_id"] for a in r.get("angles") or [])}
        if len(r.get("angles") or []) >= 2 and not (mine & taken) and _jac(r["title"], lead["title"]) < JONGHAP_SAME_TITLE:
            second = r
            break
    return lead, second, why


JONGHAP_MIN, JONGHAP_MAX = 3, 6   # 종합면 기사 수 (S47). 3건이 안 되면 종합면 없음
JONGHAP_MAIN_MAX, JONGHAP_SECOND_MIN, JONGHAP_SECOND_MAX, JONGHAP_TOTAL = 5, 2, 3, 7   # S49 각도별: 메인 3~5, 둘째 2~3, 합 7
JONGHAP_MAIN_WITH_SECOND = 4   # 둘째 묶음이 있으면 메인은 4건까지
JONGHAP_SAME_TITLE = 0.5          # 제목이 이만큼 겹치면 같은 기사로 보고 하나만


def _shown_ids(sections: list[dict], hosts: list[dict]) -> set[str]:
    """지면에 이미 실린 이슈 (예비 기사 빼고). 묶음 중심 기사의 합친 이슈는 후보로 다시 허용 (S49 — 둘째 이슈도 메인처럼)."""
    shown = {h["issue_id"] for h in hosts}
    for s in sections:
        for r in s["items"]:
            if r.get("reserve"):   # 예비 기사(쪽이 남을 때만 단신·더 읽을 기사)는 종합면에 쓰면 거기서 뺀다
                continue
            shown |= {r["issue_id"], *r.get("merged", []), *(x["issue_id"] for x in r.get("related", []))}
    for h in hosts:
        shown -= set(h.get("merged", []))
    return shown


def has_content(a: dict) -> bool:
    """창에 보일 내용(리드·한국어 요약·AI 정리)이 있는 기사 (S51 ② — 국내외 RSS 다수가 리드 없이 온다)."""
    llm = a.get("llm") or {}
    return bool((a.get("lead") or "").strip() or llm.get("ko_summary") or (llm.get("analysis") or {}).get("summary"))


def content_first(xs: list[dict]) -> list[dict]:
    """종합면 후보 순서: 내용 있는 기사 먼저(같은 안에선 원래 순서) — 빼지는 않는다 (S51 계획 결정 18)."""
    return sorted(xs, key=lambda a: not has_content(a))


def _pick_planned(host: dict, plan_angles: dict, shown: set[str], used: set[str], lo: int, hi: int) -> list[tuple[dict, str]]:
    """계획(각도·dup)대로 고르기 (S49): 점수 순(편집이 붙인 angles 순서)으로 ① 각도가 안 겹치게 hi 건까지 ② lo 건이 안 되면 같은 각도도
    lo 건까지. dup 은 가리키는 기사가 이 묶음 중심이거나 이미 고른 후보일 때만 뺀다(서로 가리키면 점수 높은 쪽이 남음)."""
    pool = [(a, plan_angles[a["issue_id"]]) for a in content_first(host.get("angles") or [])
            if a["issue_id"] not in shown and a["issue_id"] not in used and a["issue_id"] in plan_angles
            and plan_angles[a["issue_id"]].get("angle") != "무관"   # 다른 사건은 싣지 않음 (S51 ③)
            and not (plan_angles[a["issue_id"]].get("angle") == "기타" and not has_content(a))]   # AI 도 각도를 못 붙였고 보일 내용도 없는 후보 (11/17 "창업기업…")
    pool = sorted(pool, key=lambda x: x[1].get("angle") == "기타")   # 기타는 맨 뒤 (S51 결정 18)
    kept: list[tuple[dict, str]] = []

    def dup(g) -> bool:
        return bool(g.get("dup")) and (g.get("dup_of") == host["issue_id"] or g.get("dup_of") in {k["issue_id"] for k, _ in kept})

    seen: set[str] = set()
    for a, g in pool:
        ang = g.get("angle") or "기타"
        if len(kept) < hi and ang not in seen and not dup(g):
            kept.append((a, ang))
            seen.add(ang)
    for a, g in pool:
        if len(kept) >= lo:
            break
        if all(a is not k for k, _ in kept) and not dup(g):
            kept.append((a, g.get("angle") or "기타"))
    order = {id(a): n for n, (a, _) in enumerate(pool)}
    return sorted(kept, key=lambda x: order[id(x[0])])


def jonghap(sections: list[dict], title: str, row, plan: dict | None = None, second: dict | None = None, fold: bool = False) -> None:
    """종합면 (S47 → S49 각도별). 1면 메인 기사의 같은 사건 다른 기사(angles — 편집이 붙임)에서 고른다.
    plan(edition["jonghap_plan"], enrich 가 AI 로 각도·같은 내용을 판정)이 있고 메인이 같으면: 각도가 겹치지 않게 메인 묶음 3~5건 +
    둘째 이슈 묶음 2~3건(합 7). 없으면 S47 방식(다른 매체, 제목이 거의 같은 것은 하나, 3~6건). 1면 바로 뒤에 둔다."""
    from .headlines import _jac

    front = next((s for s in sections if s["id"] == "front"), None)
    lead = front and front.get("lead")
    if not lead:
        return
    groups = {g["host"]: g for g in (plan or {}).get("groups", [])}
    planned = bool(plan) and plan.get("lead") == lead["issue_id"] and lead["issue_id"] in groups
    hosts = [lead] + ([second] if planned and second is not None and second["issue_id"] in groups else [])
    shown = _shown_ids(sections, hosts)
    picked: list[tuple[dict, str | None, int]] = []   # (후보, 각도, 묶음 번호)
    if planned:
        used: set[str] = set()
        lo = 1 if fold else JONGHAP_MIN   # 창으로 접을 땐 쪽을 채울 필요가 없어 한 건이라도 (S51 — 11/17 메인 후보 대부분이 리드 없음)
        # 기존 판과 같은 기준(3건)으로 먼저 고르고, 모자랄 때만 접기용 1건 기준 — 묶음이 기존 판에 실릴 땐 건수가 같게 (재리뷰 M1)
        main = _pick_planned(lead, groups[lead["issue_id"]]["angles"], shown, used, JONGHAP_MIN, JONGHAP_MAIN_MAX)
        if fold and len(main) < JONGHAP_MIN:
            main = _pick_planned(lead, groups[lead["issue_id"]]["angles"], shown, used, 1, JONGHAP_MAIN_MAX)
        if len(main) < lo and not fold:   # 접을 땐 메인이 비어도 둘째 이슈 각도는 붙인다
            return
        used |= {a["issue_id"] for a, _ in main}
        picked += [(a, ang, 0) for a, ang in main]
        if len(hosts) > 1:
            sec = _pick_planned(second, groups[second["issue_id"]]["angles"], shown | {lead["issue_id"]}, used,
                                JONGHAP_SECOND_MIN, JONGHAP_SECOND_MAX)
            if fold and len(sec) < JONGHAP_SECOND_MIN:
                sec = _pick_planned(second, groups[second["issue_id"]]["angles"], shown | {lead["issue_id"]}, used, 1, JONGHAP_SECOND_MAX)
            if fold and sec:   # 둘째 묶음이 기존 판에 실릴 만하면(2건↑) 메인은 기존 판처럼 4건 — 두 판의 건수를 같게
                if len(sec) >= JONGHAP_SECOND_MIN:
                    picked = picked[:JONGHAP_MAIN_WITH_SECOND]
                picked += [(a, ang, 1) for a, ang in sec[: max(len(sec), 0) if len(sec) < JONGHAP_SECOND_MIN else JONGHAP_TOTAL - len(picked)]]
            elif len(sec) >= JONGHAP_SECOND_MIN:
                # 둘째 묶음이 있으면 메인 묶음은 4건까지 (종합면 두 쪽에 둘째 묶음이 실리게 — S49 견본 패드에서 5+3 이면 둘째가 1건만 남음)
                picked = picked[:JONGHAP_MAIN_WITH_SECOND]
                picked += [(a, ang, 1) for a, ang in sec[: JONGHAP_TOTAL - len(picked)]]
    else:
        srcs, titles = {lead.get("source")}, [lead["title"]]
        for a in content_first(lead.get("angles") or []):   # 내용 있는 후보 먼저 (S51 ②)
            if len(picked) >= JONGHAP_MAX:
                break
            if a["issue_id"] in shown or a.get("source") in srcs or any(_jac(a["title"], t) >= JONGHAP_SAME_TITLE for t in titles):
                continue
            picked.append((a, None, 0))
            srcs.add(a.get("source"))
            titles.append(a["title"])
        if len(picked) < (1 if fold else JONGHAP_MIN):
            return
    ids = {a["issue_id"] for a, _, _ in picked}
    for s in sections:
        s["items"] = [r for r in s["items"] if r["issue_id"] not in ids]
    if fold:   # 큐레이션 판 (S51 ②④, 시안 A): 종합면 대신 각 중심 기사의 창에 "다른 각도" — 고르기는 기존 판과 같다
        hosts_by = {0: [lead, *(s["items"][0] for s in sections if s["id"] == "detail" and s["items"])], 1: [second] if second is not None else []}
        for grp in (0, 1):
            ang_rows = []
            for a, ang, g in picked:
                if g != grp:
                    continue
                v = row(a).get("view") or {"title": a.get("title"), "lead": a.get("lead")}
                ang_rows.append({"issue_id": a["issue_id"], "angle": ang or "관련", "title": v["title"], "source": a.get("source"),
                                 "url": a.get("url"), "lang": v.get("lang"),
                                 "summary": (v.get("lead") or ((a.get("llm") or {}).get("analysis") or {}).get("summary") or "") if has_content(a) else ""})
            for h in hosts_by[grp]:
                if ang_rows:
                    h["angle_rows"] = ang_rows
        return
    rows = []
    for n, (a, ang, grp) in enumerate(picked):
        r = {**row(a), "reserve": False, "jh_group": grp}
        first_of_group = n == 0 or picked[n - 1][2] != grp
        r["jh_angle"] = None if (grp == 0 and n == 0) else ang   # 메인 묶음 첫 기사만 각도 칸 없음 (시안 B)
        if grp == 1 and first_of_group:
            g = groups[second["issue_id"]]
            r["jh_band"] = g.get("band") or second["view"]["title"]
        rows.append(r)
    if rows and not rows[0].get("photo") and picked[0][0].get("photo_alt"):   # 첫 기사 사진: RSS 대표 이미지로라도 (S47)
        rows[0]["photo"], rows[0]["photo_source"] = larger_photo(picked[0][0]["photo_alt"]), picked[0][0].get("photo_alt_source")
    for r in rows[1:]:   # 사진은 첫 기사만
        r["photo"] = None
    band = (groups[lead["issue_id"]].get("band") or lead["view"]["title"]) if planned else None   # 이름이 없어도 "이름 · 기사 n건" (구현 리뷰 M6)
    at = next((k for k, s in enumerate(sections) if s["id"] == "front"), -1) + 1
    sections.insert(at, {"id": "jonghap", "title": title, "items": rows, "theme": band or lead["view"]["title"],
                         "theme_named": planned})


CURATE_SECTIONS = ("politics", "economy", "international", "society", "interest")   # 종합면은 큐레이션 판에서 창으로 접힘 (S51)


def _on_paper(r: dict) -> bool:
    """국내 신문 지면 신호 (S50): 그 신문이 A1(naver_a1 머리기사)이나 A2~A6면(pages_by)에 실었다."""
    return any(v[1] == "naver_a1" for v in (r.get("headline_by") or {}).values()) or bool(r.get("pages_by"))


DOMESTIC = ("politics", "economy", "society")


def _curate_order(sid: str, rest: list[dict], rank: list[str] | None) -> list[dict]:
    """면 머리를 뺀 후보의 중요도 순서 (S51 ⑦). AI 순위가 있으면 그 순서(빠진 id 는 뒤에 점수 순),
    없으면 국내 면(정치·경제·사회)은 신문 지면 신호 먼저, 그다음 종합 점수 순. "보장 기사 먼저"는 쓰지 않는다
    (11/17 국제면: "다양성: 주목도 상위" 기사들이 종합 점수 2위 네타냐후를 목록으로 밀어냈다)."""
    by_score = sorted(rest, key=lambda r: -float((r.get("scores") or {}).get("final") or 0))
    fallback = sorted(by_score, key=lambda r: not _on_paper(r)) if sid in DOMESTIC else by_score
    if rank:   # AI 순위 + 빠진 기사는 대체 규칙 순서로 (구현 리뷰 M6)
        by_id = {r["issue_id"]: r for r in rest}
        ranked = [by_id[i] for i in rank if i in by_id]
        return ranked + [r for r in fallback if all(r is not x for x in ranked)]
    return fallback


def curate(sections: list[dict], ccfg, rank: dict[str, list[str]] | None = None) -> None:
    """큐레이션 판 (S50 시안 B): 뉴스 면마다 면 머리 + 중요도 순(_curate_order — AI 순위, 없으면 국내 면은 신문 지면 신호 먼저·점수 순)으로 정한 수만 기사 꼴로 남기고,
    나머지는 면 끝 "함께 볼 기사"(sec["more"], list_max 건까지) — 그 기사 창이 열리게 원본은 숨은 칸(curated_src)에.
    목록 상한을 넘긴 것은 단신 후보로. 어떤 기사도 사라지지 않는다. front_single·jonghap 뒤에 부른다(두 판의 1면·종합면 고르기가 같게)."""
    briefs = next((s for s in sections if s["id"] == "briefs"), None)
    src: list[dict] = []
    for s in sections:
        k = ccfg.keep.get(s["id"])
        if s["id"] not in CURATE_SECTIONS:
            continue
        items = [r for r in s["items"] if not r.get("reserve")]
        reserve = [r for r in s["items"] if r.get("reserve")]   # 면에 딸린 예비 기사는 쪽 나누기가 따로 다룬다 — 그대로
        if k and len(items) > k:
            head, rest = items[0], items[1:]
            order = _curate_order(s["id"], rest, (rank or {}).get(s["id"]))
            kept = [head] + order[: k - 1]
            if not (rank or {}).get(s["id"]):   # 대체 규칙: 고른 것은 원래 순서로 (AI 순위가 있으면 그 순서로 싣는다 — S51 결정 17)
                kept = [head] + [r for r in rest if any(r is x for x in kept[1:])]
            ids = {id(r) for r in kept}
            out = [r for r in order if id(r) not in ids]   # 목록도 같은 순서 (S51 N8)
            for r in out:   # 종합면 묶음 표시는 목록·창·단신에선 뜻이 없다
                for f in ("jh_angle", "jh_band", "jh_group"):
                    r.pop(f, None)
                r["home_section"] = s["id"]   # 숨은 원본·단신으로 가도 원래 면 (계획 리뷰 4차 N2)
            listed, over = out[: ccfg.list_max], out[ccfg.list_max:]
            if briefs is None:   # 단신 면이 없는 날은 목록에 모두
                listed, over = out, []
            s["items"] = kept + reserve
            s["more"] = [{"issue_id": r["issue_id"], "title": r["view"]["title"], "source": r.get("source"),
                          "topic": r.get("topic"), "url": r.get("url")} for r in listed]
            src += listed
            if over:
                briefs["items"] += over
        heads = [r for r in s["items"] if not r.get("reserve")]
        if heads:
            heads[0]["sec_head"] = True
    if src:
        sections.append({"id": "curated_src", "title": "", "items": src})


REVIEW_SCORES = ("attention", "importance", "headline", "continuity", "interest", "final")


def review_list(sections: list[dict]) -> list[dict]:
    """설정 창 "편집 리뷰" 탭 (S38b): 뉴스 면에 실은 기사(예비 제외)를 면 순서·면 안 순번으로.
    점수·분야를 같이 넘겨 기기가 리뷰와 함께 보낸다 — 발행 쪽 edition.json 이 없어져도 학습할 수 있게 (worker/src/reviews.js)."""
    out = []
    for s in sections:
        if s["id"] not in NEWS_SECTIONS:
            continue
        rows = ([s["lead"]] if s.get("lead") else []) + [r for r in s["items"] if not r.get("reserve")]
        for n, r in enumerate(rows, 1):
            sc = r.get("scores") or {}
            out.append({"id": r["issue_id"], "t": r["view"]["title"][:90], "s": s["id"], "tp": r.get("topic") or "", "r": n,
                        "sc": {k: min(1.0, max(0.0, round(float(sc.get(k) or 0), 4))) for k in REVIEW_SCORES},
                        "why": ", ".join(r.get("reasons", []))[:120]})
    return out


def editing_view(cfg: Config) -> dict:
    """설정 창 "편집 기준" 탭 (S38d): 지금 쓰는 값(자동 조정을 덮은 cfg)과 config.yaml 값, 고르는 규칙, 자동 조정 내역."""
    from . import review
    from .settings import load_config

    base = load_config(learned=False)
    keys = ("attention", "importance", "headline", "interest", "continuity", "front_headline")
    ed = cfg.editing
    got = read_json(review.learned_path(ROOT), None)
    learned = None
    if isinstance(got, dict):
        learned = {k: got.get(k) for k in ("week", "edition", "reviews", "changes", "reset_at")}
        learned["history"] = (got.get("history") or [])[-4:]
    return {
        "w": {k: getattr(cfg.weights, k) for k in keys}, "bw": {k: getattr(base.weights, k) for k in keys},
        "ti": dict(cfg.importance.topic_weights), "bti": dict(base.importance.topic_weights),
        "kwBonus": cfg.importance.keyword_bonus,
        "rules": {"diversity": ed.diversity_ratio, "contDays": ed.continuity_min_days, "contMax": ed.continuity_max_ratio,
                  "interestCap": ed.interest_cap, "topicMax": dict(ed.topic_max_ratio)},
        "learned": learned,
    }


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
    from .textutil import opinion_key

    out: dict[str, list[dict]] = {}
    seen: set = set()
    for o in sorted(op.get("editorials", []) + op.get("columns", []), key=lambda o: o.get("kind") != "editorial"):
        k = opinion_key(o.get("source"), o.get("title", ""))   # 같은 글이 다른 주소로 두 번 (S51 ⑧)
        if not o.get("issue_id") or o["url"] in seen or (k[1] and k in seen):   # 빈 제목은 같은 글로 보지 않음 (재리뷰 N3)
            continue
        seen |= {o["url"], k}
        out.setdefault(o["issue_id"], []).append({**o, "cls": LEAN_CLASS.get(o.get("lean"), "mid")})
    return out


def build_context(edition: dict, cfg: Config, interests: Interests, sources: Sources, variant: str | None = None) -> dict:
    from .textutil import fix_kana_tree

    edition = fix_kana_tree(edition)   # AI 한국어 글에 섞인 가나 → 한글 (S51 ⑥) — 한글이 든 글만, 원문 일본어 제목은 그대로
    d = date.fromisoformat(edition["edition"])
    titles = {s.id: s.title for s in cfg.sections}
    compare_ids = {it["issue_id"] for it in edition.get("compare", [])}
    rel_ops = related_opinions(edition.get("opinion"))

    def row(it: dict) -> dict:
        view = _display(it, interests.foreign_display)
        rep = next((a for a in it["articles"] if a.get("url") == it.get("url")), it["articles"][0])
        return {
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
        }

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
        if s.id == "china":   # 중국은 지금 (S37): AI 가 실기로 한 날만
            cn = edition.get("china")
            if cn:
                sections.append({"id": "china", "title": titles[s.id], "items": [], "china": {
                    **cn, "compare": [{**c, "cls": LEAN_CLASS.get(c.get("lean"), "mid"), "short": SHORT_NAME.get(c["source"], c["source"]),
                                       "flag": COUNTRY_KO.get(c.get("country"), c.get("country"))} for c in cn.get("compare", [])]}})
            continue
        items = edition["sections"].get(s.id, [])
        if not items:
            continue
        sections.append({"id": s.id, "title": titles[s.id], "items": [row(it) for it in items]})
    country = {s.name: s.country for s in sources.sources}
    front_single(sections, country)
    # 종합면 (S47·S49): 둘째 이슈는 enrich 와 같은 함수로 — 원본 기사 순서(설정의 면 순서)에서 다시 계산해 계획과 견준다
    plan = edition.get("jonghap_plan")
    second = None
    if plan:
        _, sec_raw, _ = jonghap_hosts([(s.id, edition["sections"].get(s.id, [])) for s in cfg.sections], country)
        want = next((g["host"] for g in plan.get("groups", [])[1:]), None)
        if sec_raw is not None and sec_raw["issue_id"] == want:
            second = next((r for x in sections for r in x["items"] if r["issue_id"] == want), None)   # 지면에 없으면 둘째 묶음 없음
    jonghap(sections, titles.get("jonghap", "종합"), row, plan, second, fold=variant == "b" and cfg.curated.enabled)
    if variant == "b" and cfg.curated.enabled:
        curate(sections, cfg.curated, edition.get("curate_rank"))   # S50: 큐레이션 판 — 1면·종합면을 고른 뒤. S51: AI 중요도 순위
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


def render_html(edition: dict, cfg: Config, interests: Interests, sources: Sources, base: str = "",
                variant: str | None = None) -> str:
    """지면 HTML 한 장. base 는 정적 파일까지의 상대 경로 앞부분 (지난 호 페이지는 "../../").
    variant="b" 는 큐레이션 판 (S50) — S53 부터 이것 하나만 발행한다 (주소는 기존과 같음)."""
    curated = variant == "b" and cfg.curated.enabled
    ctx = build_context(edition, cfg, interests, sources, variant="b" if curated else None)
    ctx["base"] = base
    ctx["curated"] = curated
    ctx["today_href"] = base or "./"
    ctx["is_today"] = base == ""
    client = _client_config(edition, cfg, interests, date.fromisoformat(edition["edition"]))
    client["base"] = base
    # 편집 리뷰는 기존 판 목록으로 (S50 — 같은 호 학습에 두 판의 순번이 섞이지 않게)
    client["review"] = review_list(build_context(edition, cfg, interests, sources)["sections"] if curated else ctx["sections"])
    if curated:
        client["curated"] = True
        client["sectionPages"] = {**client["sectionPages"], **cfg.curated.pages}
        client["sectionCaps"] = {**client["sectionCaps"], **cfg.curated.keep}
    client["editing"] = editing_view(cfg)
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
    write_atomic(site / "manifest.webmanifest", json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    sw = (ROOT / "templates" / "sw.js").read_text(encoding="utf-8").replace("__VER__", asset_version())
    write_atomic(site / "sw.js", sw, encoding="utf-8")


def render(edition: dict, cfg: Config, interests: Interests, sources: Sources, out_dir: Path, variant: str | None = None) -> Path:
    """로컬 미리 보기 한 장. variant="b" 면 큐레이션 판 (pipeline render 명령은 발행과 같은 판으로, S53).
    시험(make_site)은 기존 판 배치 회귀를 계속 보려고 기본값(기존 판)을 쓴다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    write_atomic(out_dir / "index.html", render_html(edition, cfg, interests, sources, variant=variant), encoding="utf-8")
    write_assets(out_dir, masthead(date.fromisoformat(edition["edition"])))
    return out_dir / "index.html"


def lead_record(edition: dict, cfg: Config, interests: Interests, sources: Sources) -> dict | None:
    """지면 첫 쪽의 1면 메인 제목(지난 호 목록의 하이라이트)과 판정 기록 (2026-11-06)."""
    front = next((s for s in build_context(edition, cfg, interests, sources)["sections"] if s["id"] == "front"), None)
    if not front or not front.get("lead"):
        return None
    return {"title": front["lead"]["view"]["title"], "note": front["lead_note"]}


def render_archive_index(dates: list[date], base: str = "../", highlights: dict[str, str] | None = None) -> str:
    """지난 호 목록. highlights: {호 날짜: 1면 메인 제목} — 기록이 없는 호는 비워 둔다."""
    highlights = highlights or {}
    return _env().get_template("archive.html.j2").render(
        base=base, items=[{"date": d.isoformat(), "name": masthead(d), "highlight": highlights.get(d.isoformat()),
                           "day": f"{'월화수목금토일'[d.weekday()]}요일"} for d in dates])
