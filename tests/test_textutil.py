from datetime import datetime, timezone

import pytest

from pipeline.textutil import LEAD_MAX, cap_lead, clean_text, detect_lang, normalize_url, parse_date, title_key

UTC = timezone.utc


@pytest.mark.parametrize(
    "raw, country, expect",
    [
        ("Thu, 15 Oct 2026 21:11:00 +0900", "KR", datetime(2026, 10, 15, 12, 11, tzinfo=UTC)),
        ("Wed, 14 Oct 2026 20:00:00 GMT", "KR", datetime(2026, 10, 14, 20, 0, tzinfo=UTC)),
        ("2026-10-15T21:20:03+09:00", "KR", datetime(2026, 10, 15, 12, 20, 3, tzinfo=UTC)),
        ("2026-10-15T12:20:03Z", "US", datetime(2026, 10, 15, 12, 20, 3, tzinfo=UTC)),
        ("Thu, 15 Oct 2026 08:07:56 -0400", "US", datetime(2026, 10, 15, 12, 7, 56, tzinfo=UTC)),
        # 시간대 없음 → 매체 국가 현지 시각
        ("2026-10-15 21:00:00", "KR", datetime(2026, 10, 15, 12, 0, tzinfo=UTC)),
        ("2026-10-15T21:00:00", "JP", datetime(2026, 10, 15, 12, 0, tzinfo=UTC)),
        ("2026.10.15 21:00", "KR", datetime(2026, 10, 15, 12, 0, tzinfo=UTC)),
    ],
)
def test_parse_date(raw, country, expect):
    assert parse_date(raw, country) == expect


@pytest.mark.parametrize("raw", [None, "", "   ", "어제 오후", "not a date"])
def test_parse_date_unparseable(raw):
    assert parse_date(raw, "KR") is None


def test_normalize_url_strips_tracking():
    a = normalize_url("https://www.example.com/news/1?utm_source=rss&utm_medium=feed&id=7#top")
    b = normalize_url("http://example.com/news/1/?id=7&fbclid=abc")
    c = normalize_url("https://m.example.com/news/1?id=7&plink=RSSREADER")
    assert a == b == c == "https://example.com/news/1?id=7"


def test_normalize_url_keeps_identity_params():
    assert normalize_url("https://x.com/a?news_id=1") != normalize_url("https://x.com/a?news_id=2")


def test_clean_text_strips_html():
    assert clean_text('<span style="c">[단독]</span> 제목 &amp; 부제') == "[단독] 제목 & 부제"


def test_cap_lead():
    short = "짧은 리드."
    assert cap_lead(short) == short
    for long in ("가나다라마바사. " * 100, "가" * 1000, "word " * 300):
        capped = cap_lead(long)
        assert len(capped) <= LEAD_MAX
        assert capped.endswith("…")


def test_title_key_ignores_prefix_and_punct():
    assert title_key("[단독] 삼성전자, HBM 공급 확대") == title_key("삼성전자 HBM 공급 확대!")


@pytest.mark.parametrize(
    "text, lang",
    [
        ("李대통령 “개헌”", "ko"),
        ("相次ぐ不正アクセス", "ja"),
        ("中国经济增长放缓", "zh"),
        ("TSMC profit soars 69%", "en"),
        ("الجزيرة", "ar"),
        ("12345", "und"),
    ],
)
def test_detect_lang(text, lang):
    assert detect_lang(text) == lang
