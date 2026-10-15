"""입장 차이 (무토큰): 같은 이슈를 성향 축·국가 축으로 나란히 놓고, 그룹마다 특징 단어를 뽑는다.

- 성향 축: 보수 / 중도 / 진보 / 경제지 / 통신·공영 / 관영
- 국가 축: 한국 / 미국 / 영국 / 일본 / 중국 / 중동
- 특징 단어: 같은 언어 기사끼리만 비교한다 (한국어와 영어 단어를 비교하면 "언어 차이"만 나온다).
  그룹 하나 대 나머지의 log-odds (Monroe·Colaresi·Quinn 2008, 그날 같은 언어 전체를 사전분포로).
  같은 사건을 어떤 단어로 부르는지 차이를 드러내는 것이 목적이다.
- "○○ 매체만 보도": 한쪽 성향 또는 한쪽 나라 매체만 다룬 이슈 표시
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .collect import Article

COUNTRY_LABEL = {"KR": "한국", "US": "미국", "UK": "영국", "JP": "일본", "CN": "중국", "QA": "중동"}
LEAN_ORDER = ["보수", "중도", "진보", "경제지", "통신·공영", "관영"]
COUNTRY_ORDER = ["KR", "US", "UK", "JP", "CN", "QA"]

_JOSA = re.compile(
    r"(으로부터|에게서|이라며|라며|이라고|라고|에서는|에서도|으로는|으로도|에서|에게|까지|부터|으로|처럼|보다|"
    r"이며|하며|한다|했다|하고|에는|에도|과의|와의|이나|이란|란|은|는|이|가|을|를|에|의|도|로|과|와|만|께|서)$"
)
_KO_WORD = re.compile(r"[가-힣A-Za-z0-9]+")
_EN_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]+")
# 보도 상투어 (프레임이 아니라 기사 문체에서 나오는 말)와 매체 이름
STOP_KO = {
    "속보", "단독", "종합", "포토", "사진", "영상", "오늘", "내일", "어제", "이번", "지난", "올해", "관련", "위해", "대해",
    "통해", "기자", "특파원", "서울", "이날", "오전", "오후", "밝혔", "말했", "전했", "따르면", "설명", "강조", "덧붙",
    "연합뉴스", "뉴시스", "뉴스1", "조선일보", "중앙일보", "동아일보", "한겨레", "경향신문", "한국경제", "매일경제",
    "KBS", "SBS", "MBC", "YTN", "OSEN", "그러면서", "한편", "또한", "이어", "현재", "당시", "최근", "가운데", "것으로",
}
_VERB_END = re.compile(r"(했다고|했다며|했다는|했다|한다고|한다며|된다고|됐다고|됐다|된다|하는|하며|하고|해야|이라는|라는|다고|다며|한|된|할|될)$")
_NUM_UNIT = re.compile(r"[0-9][0-9.,]*(일|월|년|시|분|초|명|건|개|곳|만|억|조|원|달러|%|세|차|번째|대)?")
STOP_KO_PRED = {"있다", "없다", "했다", "된다", "한다", "이다", "아니다", "같다", "보인다", "나왔다"}
STOP_EN = set(
    """a an the and or but of to in on at for from by with as is are was were be been being it its this that these
    those after before over under about into than then there their they them he she his her we our you your not no
    will would can could may might says said say new more most up out off amid how what why who when where which while
    just has have had do does did us also first last one two three latest live update told according reported
    reports reuters cnn bbc nyt guardian news week day days year years time people earlier later done run least
    including amid since like used using make made get got take took""".split()
)


def words(text: str, lang: str) -> list[str]:
    """표시할 수 있는 낱말 단위 (특징 단어는 사람이 읽어야 하므로 글자 조각이 아닌 낱말)."""
    out = []
    if lang == "ko":
        for w in _KO_WORD.findall(text):
            if _NUM_UNIT.fullmatch(w) or w in STOP_KO_PRED:
                continue
            stem = _VERB_END.sub("", w)
            base = stem if len(stem) >= 2 else w
            base = _JOSA.sub("", base) if len(base) > 2 else base
            if len(base) >= 2 and base not in STOP_KO and not any(base.startswith(x) for x in ("밝혔", "말했", "전했")):
                out.append(base)
    elif lang == "en":
        for w in _EN_WORD.findall(text):
            w = w.lower().strip("'-")
            w = re.sub(r"'s$", "", w)
            if len(w) >= 3 and w not in STOP_EN:
                out.append(w)
    return out


def group_lean(a: Article) -> str:
    return a.lean


def group_country(a: Article) -> str:
    return a.country


def log_odds(groups: dict[str, Counter], prior: Counter, prior_scale: float = 0.1) -> dict[str, list[tuple[str, float]]]:
    """그룹 하나 대 나머지의 사전분포 보정 log-odds z 점수 (높을수록 그 그룹에 특징적)."""
    a0_total = sum(prior.values()) or 1
    alpha = {w: prior_scale * c * 100 / a0_total + 0.01 for w, c in prior.items()}
    a0 = sum(alpha.values())
    out = {}
    for g, cnt in groups.items():
        rest = Counter()
        for h, c in groups.items():
            if h != g:
                rest.update(c)
        n_i, n_j = sum(cnt.values()), sum(rest.values())
        scores = []
        for w in cnt:
            aw = alpha.get(w, 0.01)
            yi, yj = cnt[w], rest.get(w, 0)
            d = math.log((yi + aw) / (n_i + a0 - yi - aw)) - math.log((yj + aw) / (n_j + a0 - yj - aw))
            var = 1 / (yi + aw) + 1 / (yj + aw)
            scores.append((w, d / math.sqrt(var)))
        scores.sort(key=lambda x: (-x[1], x[0]))
        out[g] = scores
    return out


def distinctive_words(
    arts: list[Article], key, prior_by_lang: dict[str, Counter], top: int = 3, min_z: float = 0.7
) -> dict[str, list[str]]:
    """같은 언어 기사끼리, key 로 나눈 그룹이 둘 이상일 때만 그룹별 특징 단어를 낸다."""
    result: dict[str, list[str]] = {}
    for lang in sorted({a.lang for a in arts}):
        same = [a for a in arts if a.lang == lang]
        groups: dict[str, Counter] = {}
        for a in same:
            c = groups.setdefault(key(a), Counter())
            c.update(set(words(a.title, lang)))      # 제목 단어는 두 번 센다 (프레임은 제목에 가장 잘 드러난다)
            c.update(set(words(f"{a.title} {a.lead}", lang)))
        if len(groups) < 2:
            continue
        lo = log_odds(groups, prior_by_lang.get(lang, Counter()))
        for g, scored in lo.items():
            picked = [w for w, z in scored if z >= min_z][:top]
            if picked:
                result.setdefault(g, [])
                result[g] += [w for w in picked if w not in result[g]]
    return result


def coverage_note(arts: list[Article]) -> str | None:
    """한쪽만 보도한 이슈 표시 — 당연한 경우(국내 기사만 있는 국내 이슈, 매체 1곳뿐인 기사)는 말하지 않는다.
    - 해외 한 나라 매체만 다룬 이슈: "미국 매체만 보도" (국내·다른 나라 보도 없음)
    - 국내 매체 2곳 이상이 다뤘는데 보수·진보 한쪽이 빠진 이슈: "국내 진보 성향 매체 보도 없음"
    """
    if len({a.source for a in arts}) < 2:
        return None
    notes = []
    countries = {a.country for a in arts}
    if len(countries) == 1 and "KR" not in countries:
        c = next(iter(countries))
        notes.append(f"{COUNTRY_LABEL.get(c, c)} 매체만 보도")
    kr = [a for a in arts if a.country == "KR"]
    kr_leans = {a.lean for a in kr}
    if len({a.source for a in kr}) >= 2:
        if "보수" in kr_leans and "진보" not in kr_leans:
            notes.append("국내 진보 성향 매체 보도 없음")
        elif "진보" in kr_leans and "보수" not in kr_leans:
            notes.append("국내 보수 성향 매체 보도 없음")
    return " · ".join(notes) or None


def day_prior(all_articles: list[Article]) -> dict[str, Counter]:
    prior: dict[str, Counter] = {}
    for a in all_articles:
        prior.setdefault(a.lang, Counter()).update(set(words(f"{a.title} {a.lead}", a.lang)))
    return prior


def stance(arts: list[Article], prior: dict[str, Counter]) -> dict:
    by_lean: dict[str, list[dict]] = {}
    by_country: dict[str, list[dict]] = {}
    for a in arts:
        row = {"source": a.source, "title": a.title, "lead": a.lead, "url": a.url, "lang": a.lang}
        by_lean.setdefault(a.lean, []).append(row)
        by_country.setdefault(a.country, []).append(row)
    return {
        "lean": [{"group": g, "articles": by_lean[g]} for g in LEAN_ORDER if g in by_lean],
        "country": [{"group": COUNTRY_LABEL.get(c, c), "code": c, "articles": by_country[c]} for c in COUNTRY_ORDER if c in by_country],
        "lean_words": distinctive_words(arts, group_lean, prior),
        "country_words": {COUNTRY_LABEL.get(k, k): v for k, v in distinctive_words(arts, group_country, prior).items()},
        "note": coverage_note(arts),
    }
