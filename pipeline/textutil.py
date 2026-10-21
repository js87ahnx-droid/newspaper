"""날짜·URL·텍스트·언어 처리 — 수집과 정제가 함께 쓴다."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

# 시간대 표기가 없는 날짜 문자열은 매체 국가의 현지 시각으로 본다
COUNTRY_TZ = {
    "KR": "Asia/Seoul",
    "JP": "Asia/Tokyo",
    "CN": "Asia/Shanghai",
    "US": "America/New_York",
    "UK": "Europe/London",
    "QA": "Asia/Qatar",
}

LEAD_MAX = 300  # 리드 길이 상한 — 본문이 통째로 들어오는 피드가 있어도 지면에는 리드 분량만 남긴다


def parse_date(raw: str | None, country: str) -> datetime | None:
    """RSS 날짜 문자열 → UTC aware datetime. 해석할 수 없으면 None."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    dt: datetime | None = None
    try:
        dt = parsedate_to_datetime(raw)  # RFC 822: "Thu, 15 Oct 2026 21:11:00 +0900"
    except (TypeError, ValueError, IndexError):
        pass
    if dt is None:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # ISO 8601
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M"):
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(COUNTRY_TZ.get(country, "UTC")))
    return dt.astimezone(timezone.utc)


_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|igshid$|mc_|ocid$|cmpid$|ref$|ref_src$|smid$|rss$|plink$|sectionid$|syn-)", re.I)


def normalize_url(url: str) -> str:
    """추적 파라미터·조각·끝 슬래시를 없애고 스킴·호스트를 통일해 같은 기사를 같은 주소로 만든다."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m.") and host.count(".") >= 2:
        host = host[2:]
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    return _WS.sub(" ", s).strip()


def cap_lead(s: str) -> str:
    """리드를 LEAD_MAX 자 이하로 줄인다 (말줄임표 포함)."""
    if len(s) <= LEAD_MAX:
        return s
    cut = s[: LEAD_MAX - 2]
    # 문장·단어 경계에서 자른다
    for sep in (". ", "다. ", "。", " "):
        i = cut.rfind(sep)
        if i >= LEAD_MAX * 0.6:
            return cut[: i + len(sep)].rstrip() + " …"
    return cut + "…"


def title_key(title: str) -> str:
    """같은 매체 안 중복 판정용 제목 키: 말머리([단독] 등)·문장부호·공백 제거, 소문자."""
    t = re.sub(r"^\s*(\[[^\]]{1,12}\]\s*)+", "", title)
    t = re.sub(r"[\W_]+", "", t, flags=re.UNICODE)
    return t.lower()


EMPTY_TITLE_MIN = 3   # 말머리·매체 이름·기호를 뺀 글자가 이보다 적으면 내용 없는 제목 ("[사설] 국감 파행"처럼 짧은 제목은 남게)


def empty_title(title: str, source_names: set[str] | frozenset[str] = frozenset()) -> bool:
    """제목이 매체 이름·말머리·기호뿐인가 (S24d: 10/19호 "- 중앙일보" 가 사흘째 이어진 이슈로 지면에 실림)."""
    t = re.sub(r"[\[\(（【][^\]\)）】]{0,12}[\]\)）】]", " ", title)   # [속보]·(종합) 같은 말머리
    for name in sorted(source_names, key=len, reverse=True):
        if name:
            t = t.replace(name, " ")
    return len(re.sub(r"[\W_]+", "", t, flags=re.UNICODE)) < EMPTY_TITLE_MIN


_HANGUL = re.compile(r"[가-힣]")
_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[一-鿿]")
_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")


def detect_lang(text: str) -> str:
    """문자 체계 기반 언어 판별: ko / ja / zh / ar / en / und. 라틴 문자는 모두 en — 프랑스어·독일어는 피드 설정(Feed.lang)으로 (S20b)."""
    if _HANGUL.search(text):
        return "ko"
    if _KANA.search(text):
        return "ja"
    if _HAN.search(text):
        return "zh"
    if _ARABIC.search(text):
        return "ar"
    if _LATIN.search(text):
        return "en"
    return "und"


_BYLINE = re.compile(r"^\s*[\(\[][^)\]]{1,30}=[^)\]]{0,20}[\)\]]\s*(?:[가-힣]{2,4}\s*){0,3}(?:기자|특파원)?\s*=\s*")
_PHOTO_CAPTION = re.compile(r"^\s*▲[^.。]*?(?=[가-힣A-Za-z]+[은는이가]\s)")
MIN_LEAD = 20


def clean_lead(lead: str) -> str:
    """지면용 리드 다듬기: 머리의 기자명·지역 표기("(서울=연합뉴스) 홍길동 기자 =")와 사진 설명("▲ …")을 걷어내고,
    20자도 안 되는 리드(속보 자리표시 "(" 등)는 없는 것으로 본다."""
    s = _BYLINE.sub("", lead or "")
    s = _PHOTO_CAPTION.sub("", s).strip()
    return s if len(s) >= MIN_LEAD else ""


# ---------- 논평·사설 판별 ----------
_ED_URL = re.compile(r"/opinion/editorial|/editorials?/|the-guardian-view-on", re.I)
_OP_URL = re.compile(r"/opinions?/|/commentisfree/|/arti/opinion/|/news/Opinion/", re.I)
_ED_TITLE = re.compile(r"\[\s*사설\s*\]|^사설\s|The Guardian view on|^Editorial\b|^GT Editorial", re.I)
_OP_TAG = re.compile(
    r"(칼럼|시론|기고|논평|오피니언|에세이|수첩|데스크|특파원|동아광장|시평|세상읽기|횡설수설|팔면봉|만물상|분수대|여적|"
    r"프리즘|오늘과 내일|광화문에서|동서남북|사유와 성찰|녹색세상|아침을 열며|편집국에서|기자의 눈)"
)
_BRACKET_TAGS = re.compile(r"^\s*\[([^\]]{1,30})\]|\[([^\]]{1,30})\]\s*$")
_PERSON_COLUMN = re.compile(r"^[가-힣]{2,4}의 \S")
_NOT_PERSON = {"오늘", "내일", "어제", "이번", "이주", "주간", "금주", "세계", "한국", "우리", "이달", "올해", "지금", "이주일", "오늘날"}


def detect_opinion(title: str, url: str, feed_section: str = "") -> str | None:
    """'editorial'(사설) / 'column'(칼럼·논평·기고) / None(뉴스).
    근거: 사설 표기("[사설]", "The Guardian view on"), 의견면 주소(/opinion/, /commentisfree/), 칼럼 머리말
    ("[朝鮮칼럼]", "[기고]", "[김경의 별잇기 예술여행]" 같은 필자 연재), 의견 피드(section: opinion)."""
    if _ED_TITLE.search(title) or _ED_URL.search(url):
        return "editorial"
    if feed_section == "opinion" or _OP_URL.search(url):
        return "column"
    for m in _BRACKET_TAGS.finditer(title):
        tag = (m.group(1) or m.group(2) or "").strip()
        person = _PERSON_COLUMN.match(tag)
        if person and tag.split("의", 1)[0] in _NOT_PERSON:  # "[오늘의 날씨]", "[내일의 국감]" 은 필자 연재가 아니다
            person = None
        if _OP_TAG.search(tag) or person:
            return "column"
    return None


# 제목 번역 + 한국어 요약을 둘 다 받는 언어 (S20b 프랑스어·독일어, S20d 중국어) — 리드를 읽을 수 없으므로
TRANSLATE_BOTH = {"fr", "de", "zh"}


# ---------- 분석·해설 기사 (S22c, 2026-10-18 사용자 요청: 매체가 쓴 분석) ----------
# 규칙은 10/18 누적분 6,617건 실측(정밀도 높은 것만): 제목 머리말·꼬리말, 주소. "Why/How" 같은 질문형 제목은 잡음이 많아 뺐다
_AN_TITLE = [
    re.compile(r"^(News\s+)?Analysis\s*[:|]|^(Explainer|Insight|Big Take|Fact check|FACT FOCUS)\s*[:|\-–]"
               r"|(?:[-–—|]\s*|\()(Analysis|Explainer)\)?\s*$", re.I),
    # "What we know about ~" 는 사건 사실 정리(속보)가 많아 뺀다 (S22c 평가: CNN 총격범 기사)
    re.compile(r"\bWhat you need to know\b|\bwhat to know\b|\btakeaways\b|(,|:)\s*explained\b|^Explained\b", re.I),
    re.compile(r"[\[〈<]\s*(뉴스\s?분석|분석\+?|해설|뉴스\s?해설|이슈\s?분석|딥\s?다이브|심층(\s?분석)?|Why|줌인|이슈\+|경제뭔데|점선면"
               r"|뉴스\s?다이브|팩트\s?체크|이슈\s?In|이슈\s?추적)\s*[\]〉>]"),
    re.compile(r"（時時刻刻）|[［【\[]\s*(解説|深層|核心|スキャナー|ニュースQ＋?|視点)\s*[］】\]]|^解説[：:]"),
    re.compile(r"^(国际观察|新华述评|深度观察|财新观察|热点观察|国际热评|述评)\s*[丨｜|:：]"),
    re.compile(r"^(Analyse|Décryptage|Récit|Enquête)\s*[:|]|[-–]\s*(analyse|décryptage)\s*$", re.I),
    re.compile(r"[-–]\s*(eine\s+)?Analyse\s*$|^Analyse\s*:"),
]
_AN_URL = re.compile(r"economist\.com/(interactive/)?(briefing|graphic-detail)/|aljazeera\.com/(news-analysis|explainer)/"
                     r"|lemonde\.fr/les-decodeurs/|ft\.com/the-big-read", re.I)
_AN_NOT = re.compile(r"\bpodcast\b|^Watch\b|\bquiz\b|war briefing|^Live\b|\bLIVE\b|^From the archive|Match of the Day"
                     r"|\b(NCAA|NFL|NBA|MLB|NHL|Premier League|World Cup|Olympics?)\b|야구|축구|농구|골프"   # 스포츠 해설 (S22c 평가)
                     r"|Latest Articles, Analysis|News & Analysis|바둑 해설|해설사", re.I)


# 인터뷰 (S27, 2026-10-21 사용자 요청: 세계 석학·철학자·구루·정치인 인터뷰 중 인사이트 있는 것) — 후보만 넉넉히, 고르기는 AI
_IV_TITLE = re.compile(
    r"[\[〈<(（]\s*(?:단독\s?|석학\s?|직격\s?|신년\s?|특별\s?)?(?:인터뷰|대담|interview)\s*[\]〉>)）]|인터뷰\s*[:|]"
    r"|^(?:Interview|Q&A|Entretien|Interview mit)\b|\bQ&A\b|\bin conversation with\b|\binterview\b"
    r"|インタビュー|专访|对话|im Interview|\bentretien\b", re.I)
_IV_LEAD = re.compile(
    r"(?:와|과)의\s?(?:화상\s?|단독\s?|서면\s?)?인터뷰|인터뷰에서|인터뷰를 통해|대담에서|\bin an interview\b|\binterview with\b"
    r"|\btold [\w’' .]{2,30} in an interview\b|\bspoke (?:to|with) [\w’' .]{2,30}(?:about|in)\b|インタビューで|接受[^。]{0,12}专访"
    r"|lors d['’]un entretien|im Interview", re.I)
_IV_NOT = re.compile(r"\b(NCAA|NFL|NBA|MLB|NHL|Premier League|World Cup|Olympics?)\b|야구|축구|농구|골프|배우|가수|아이돌|드라마|영화감독|컴백"
                     r"|\bjob interview\b|면접", re.I)


def detect_interview(title: str, lead: str = "") -> bool:
    """인터뷰 기사 후보인가 (S27). 제목 표시(〔인터뷰〕·Q&A·interview) 또는 첫 문단의 "~와의 인터뷰에서"·"in an interview".
    스포츠·연예·면접은 뺀다. 석학·정치인 등 인사이트 있는 것을 고르는 건 AI 검토(llm.review_interviews)."""
    if _IV_NOT.search(title):
        return False
    return bool(_IV_TITLE.search(title) or _IV_LEAD.search(lead or ""))


def detect_analysis(title: str, url: str, feed_section: str = "") -> bool:
    """매체가 쓴 분석·해설 기사인가 (S22c). 전용 피드(section: analysis)이거나 제목·주소 표시가 있으면."""
    if _AN_NOT.search(title) or re.search(r"/sports?/|/football/", url, re.I):   # 스포츠 면 주소 (S22c 평가: WaPo NFL 분석)
        return False
    return feed_section == "analysis" or bool(_AN_URL.search(url)) or any(p.search(title) for p in _AN_TITLE)
