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


_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|igshid$|mc_|ocid$|cmpid$|ref$|ref_src$|smid$|rss$|plink$|sectionid$)", re.I)


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


_HANGUL = re.compile(r"[가-힣]")
_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[一-鿿]")
_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")


def detect_lang(text: str) -> str:
    """문자 체계 기반 언어 판별: ko / ja / zh / ar / en / und."""
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
