"""중국은 지금 (S37, 19차 요청): 인민일보로 읽는 중국 지도부의 관점·강조점과, 같은 주제를 다른 나라 매체가 다루는 방식.

인민일보는 중국공산당 중앙위원회 기관지라 보도 자체가 당의 공식 입장·우선순위를 보여 준다.
매일 싣지 않는다 — 조건으로 후보를 고르고(watch), AI 가 중국 시각이 뚜렷이 다를 때만 싣기로 판단한다(analyze).

- watch(edition, articles): edit 단계. 그날 인민일보 기사 제목 목록(agenda)과 후보 이슈.
  후보 = 그날 종이 인민일보(top)·논평(opinion) 기사가 있을 때, 지면 이슈(예비 제외) 중 중국 관련(이슈 제목에 중국·시진핑·대만 등,
  또는 중국 밖 매체 제목 둘 이상)이고 중국 밖 2개국 이상(중국 포함 3개국 이상) 매체가 다룬 것. 종합 점수 순 3개.
  (처음엔 인민일보 기사가 같은 묶음에 든 이슈만 봤으나, 10/22 실데이터에서 중국어 기사가 다른 나라 기사와 묶인 이슈는 하루 3건뿐이고
  모두 국제 피드라 거의 안 실렸다 — 인민일보 제목과의 짝짓기는 AI 가 한다)
- analyze(watch, items, bodies, …): enrich 단계. 분석 모델 1회. 응답은 넘긴 자료 안에서만 쓰였는지 검사해 거른다
  (근거에 인민일보 기사가 하나도 없으면 싣지 않는다)
기사 본문은 프롬프트에만 쓰고 저장하지 않는다 (D16).
"""
from __future__ import annotations

import json
import re

PD = "인민일보"
PD_KEY_FEEDS = ("top", "opinion")    # top = 종이 인민일보(paper.people.com.cn), opinion = 인민망 논평
MIN_FOREIGN_COUNTRIES = 2            # 중국 밖 나라 수 (중국 포함 3개국 이상)
MAX_CANDIDATES = 3
AGENDA_MAX = 150                     # 프롬프트에 넣는 그날 인민일보 제목 수 (하루 120~270건)
ARTICLES_PER_SIDE = 6                # 후보마다 넣는 기사 수 (인민일보 쪽 / 다른 나라 쪽)
BODY_CHARS = 1200
SKIP_TITLES = ("图片报道", "责编", "邮箱")   # 판면 사진 설명·편집자 표시 (제목이 아님)
# 중국 관련 이슈 (한·영·중·일 제목). "中" 한 글자는 한국 신문 제목의 줄임("中 티베트서…")만 — 일본어 中東·中止 는 아님
CHINA_RE = re.compile(r"중국|시진핑|베이징|대만|홍콩|China|Chinese|Beijing|Xi Jinping|Taiwan|Hong Kong|中国|中國|习近平|習近平|台湾|香港"
                      r"|[美韓日北]中|中[美韓日]|미중|한중|북중|중일"
                      r"|(?:^|[\s“\"'‘(\[])中(?=[\s,·…’”\"'])", re.I)


def china_related(it: dict) -> bool:
    """이슈 제목이 중국 관련이거나, 중국 밖 매체 기사 제목 둘 이상이 중국 관련.
    (중국 매체 기사가 묶였다는 것만으로는 아님 — 10/22 실데이터: 큰 묶음에 SCMP·인민일보 기사가 하나씩 끼어 ICC·PHP 보안 이슈까지 걸렸다)"""
    if CHINA_RE.search(it["title"]):
        return True
    return sum(1 for a in it["articles"] if not _is_cn(a) and CHINA_RE.search(a["title"])) >= 2


def _is_cn(a) -> bool:
    return (a.get("country") if isinstance(a, dict) else a.country) == "CN"


def watch(edition: dict, articles: dict) -> dict:
    """edition = edition_to_json 결과, articles = {id: Article} (그날 시간창 기사 전부). 본문·리드는 담지 않는다."""
    agenda = []
    for a in sorted(articles.values(), key=lambda a: (a.published or "", a.id), reverse=True):
        if a.source != PD or any(s in a.title for s in SKIP_TITLES) or len(a.title.strip()) < 4:
            continue
        agenda.append({"id": a.id, "title": a.title.strip(), "sections": list(a.sections), "opinion": a.opinion, "url": a.url})
    agenda = agenda[:AGENDA_MAX]
    if not any(set(a["sections"]) & set(PD_KEY_FEEDS) or a["opinion"] for a in agenda):
        return {"agenda": agenda, "candidates": []}   # 그날 종이 인민일보·논평을 못 받았으면 견줄 기준이 없다

    cands = []
    for sec, items in edition.get("sections", {}).items():
        for it in items:
            if it.get("reserve") or not china_related(it):
                continue
            pd = [a for a in it["articles"] if a["source"] == PD]
            foreign = {a["country"] for a in it["articles"] if not _is_cn(a)}
            if len(foreign) < MIN_FOREIGN_COUNTRIES:
                continue
            cands.append({"issue_id": it["issue_id"], "section": sec, "title": it["title"],
                          "final": (it.get("scores") or {}).get("final", 0), "pd_ids": [a["id"] for a in pd],
                          "foreign_countries": sorted(foreign)})
    cands.sort(key=lambda c: -c["final"])
    return {"agenda": agenda, "candidates": cands[:MAX_CANDIDATES]}


SYSTEM = ("너는 중국 관영매체 보도를 읽어 내는 국제부 기자다. 주어진 자료 밖의 사실을 지어내지 않는다. "
          "인민일보는 중국공산당 중앙위원회 기관지이므로, 보도를 사실 전달이 아니라 지도부가 강조하려는 메시지로 읽는다. "
          "중국을 비난하거나 옹호하지 말고 차이를 드러낸다. 반드시 JSON 하나만 출력한다.")

PROMPT = """아래 자료로 독자가 "지금 중국이 어떤 관점에서 무엇에 중점을 두는가"를 알 수 있게 '중국은 지금' 해설을 한국어로 써라.

자료
- 인민일보_오늘: 오늘 인민일보 기사 제목 전부(섹션: top=종이 인민일보, opinion=논평). 그날 당이 무엇을 앞세우는지 보여 준다
- 후보: 오늘 우리 지면에 오른 중국 관련 이슈. 다른 나라 매체 기사(제목·본문 또는 요약)와, 같은 묶음에 든 인민일보 기사가 있으면 그것도

할 일
1. 후보마다 인민일보_오늘 제목 가운데 같은 주제를 다룬 기사를 찾는다. 인민일보가 다루지 않은 후보는 고르지 않는다.
   그 가운데 중국의 시각·강조점이 다른 나라 매체와 뚜렷이 다른 이슈 하나를 고른다(issue_id).
   차이가 평범하거나 자료가 빈약하거나 인민일보 기사를 못 찾으면 show 를 false 로 하고 reason 에 이유를 쓴다 — 억지로 싣지 마라.
2. title: 중국이 이 주제를 어떤 틀로 다루는지 드러나는 신문 제목 한 줄
3. lead: 2~3문장. 인민일보가 무엇을 앞세우고 무엇을 빼는지
4. emphasis: 인민일보가 강조하는 것 3~4개 (짧은 구)
5. omitted: 다른 나라 매체는 다루는데 인민일보는 다루지 않는 것 1~3개 — 자료에서 확인되는 것만
6. keywords: 인민일보 제목에 실제로 나온 중국어 핵심 표현 2~5개 (제목에 있는 글자 그대로)
7. compare: 다른 나라 매체마다 같은 주제의 초점 한 줄 {{"source": 자료의 매체 이름 그대로, "focus": "…"}} 2~5개 (중국 매체 제외)
8. agenda: 인민일보_오늘 제목 전체로 본 오늘 당이 앞세운 의제 2~4개 (짧은 구)
9. evidence: 근거로 쓴 기사 주소 2~5개 (자료의 url 그대로) — 인민일보 기사를 반드시 하나 이상

출력 형식:
{{"show": true, "reason": "", "issue_id": "…", "title": "…", "lead": "…", "emphasis": ["…"], "omitted": ["…"],
  "keywords": ["…"], "compare": [{{"source": "…", "focus": "…"}}], "agenda": ["…"], "evidence": ["url"]}}

{data}"""


def _rows(watch_: dict, items: dict, bodies: dict) -> dict:
    cands = []
    for c in watch_["candidates"]:
        it = items.get(c["issue_id"])
        if not it:
            continue

        def side(arts):
            out, seen = [], set()
            for a in sorted(arts, key=lambda a: bodies.get(a["url"]) is None):
                if a["source"] in seen and len(arts) > ARTICLES_PER_SIDE:
                    continue
                seen.add(a["source"])
                body = bodies.get(a["url"])
                out.append({"매체": a["source"], "나라": a["country"], "제목": a["title"], "url": a["url"],
                            "본문": body[:BODY_CHARS] if body else f"(본문 없음) {(a.get('lead') or '')[:300]}"})
            return out[:ARTICLES_PER_SIDE]
        cands.append({"issue_id": c["issue_id"], "지면 제목": it["title"],
                      "인민일보": side([a for a in it["articles"] if a["source"] == PD]),
                      "다른 나라 매체": side([a for a in it["articles"] if not _is_cn(a)])})
    agenda = [{"섹션": "opinion" if a.get("opinion") else ",".join(a["sections"]), "제목": a["title"], "url": a["url"]}
              for a in watch_["agenda"]]
    return {"인민일보_오늘": agenda, "후보": cands}


def _clean(res: dict, watch_: dict, items: dict) -> tuple[dict | None, str]:
    """AI 응답을 지면에 쓸 모양으로. 자료 밖 내용(후보 아닌 이슈·없는 매체·제목에 없는 낱말·모르는 주소)은 거른다."""
    if not isinstance(res, dict):
        return None, "응답 형식 틀림"
    if not res.get("show"):
        return None, "안 실음: " + str(res.get("reason") or "AI 판단")[:80]
    iid = str(res.get("issue_id", ""))
    if iid not in {c["issue_id"] for c in watch_["candidates"]} or iid not in items:
        return None, "후보 밖 이슈"
    it = items[iid]
    title, lead = str(res.get("title", "")).strip(), str(res.get("lead", "")).strip()
    if not title or not lead:
        return None, "제목·요약 비어 있음"

    def strs(key, n):
        return [str(x).strip() for x in res.get(key) or [] if str(x).strip()][:n]
    pd_titles = " ".join([a["title"] for a in watch_["agenda"]] + [a["title"] for a in it["articles"] if a["source"] == PD])
    keywords = [k for k in strs("keywords", 5) if k in pd_titles]
    foreign = {a["source"]: a for a in it["articles"] if not _is_cn(a)}
    compare = []
    for c in res.get("compare") or []:
        if isinstance(c, dict) and str(c.get("source")) in foreign and str(c.get("focus", "")).strip():
            a = foreign[str(c["source"])]
            if all(x["source"] != a["source"] for x in compare):
                compare.append({"source": a["source"], "country": a["country"], "lean": a["lean"], "focus": str(c["focus"]).strip()})
    if len(compare) < 2:
        return None, "다른 나라 매체 비교가 2곳 미만"
    known = {a["url"]: a for a in it["articles"]} | {a["url"]: {**a, "source": PD, "country": "CN", "lean": "관영"} for a in watch_["agenda"]}
    evidence = []
    for u in strs("evidence", 5):
        if u in known and all(e["url"] != u for e in evidence):
            a = known[u]
            evidence.append({"source": a["source"], "title": a["title"], "url": u, "lang": a.get("lang", "zh")})
    if not any(e["source"] == PD for e in evidence):
        return None, "인민일보 근거 없음"
    return {"issue_id": iid, "title": title, "lead": lead, "emphasis": strs("emphasis", 4), "omitted": strs("omitted", 3),
            "keywords": keywords, "compare": compare[:5], "agenda": strs("agenda", 4), "evidence": evidence}, "실음"


def analyze(watch_: dict | None, items: list[dict], bodies: dict, cache: dict, ask) -> tuple[dict | None, str]:
    """ask(prompt, system=…) → (응답 dict | None, 상태). 같은 후보·같은 의제면 캐시(cache["china"])."""
    if not watch_ or not watch_.get("candidates"):
        return None, "후보 없음"
    by_id = {it["issue_id"]: it for it in items}
    key = ",".join(c["issue_id"] for c in watch_["candidates"]) + "#" + str(len(watch_.get("agenda", [])))
    hit = cache.get("china")
    if isinstance(hit, dict) and hit.get("key") == key:
        res = hit.get("res")
    else:
        res, st = ask(PROMPT.format(data="<data>\n" + json.dumps(_rows(watch_, by_id, bodies), ensure_ascii=False, indent=0) + "\n</data>"),
                      system=SYSTEM)
        if res is None:
            return None, st
        cache["china"] = {"key": key, "res": res}
    return _clean(res, watch_, by_id)
