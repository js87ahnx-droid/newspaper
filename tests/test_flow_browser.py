"""흐름 누적 표시 (S29b): 오늘 앞선 보도 → 지금. 지면엔 최근 2줄 + 지금, 자세히 창엔 전부."""
import pytest

from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)

UPDATES = [
    {"published": "2026-10-21T21:14:00+00:00", "title": "뉴욕증시, 스페이스X 실적에 기술주 강세…나스닥 1.1%↑(종합)",
     "source": "연합뉴스", "url": "https://x.test/u1", "lang": "ko", "asof": "뉴욕증시 21일(현지) 마감"},
    {"published": "2026-10-22T13:53:00+00:00", "title": "뉴욕증시, AI 불안에 하락 출발",
     "source": "연합뉴스", "url": "https://x.test/u2", "lang": "ko", "asof": "뉴욕증시 22일(현지) 장중"},
    {"published": "2026-10-22T18:42:00+00:00", "title": "U.S. Stocks Fall as Tech Selloff Deepens",
     "source": "WSJ", "url": "https://x.test/u3", "lang": "en", "asof": "뉴욕증시 22일(현지) 장중"},
]


def _mut(out):
    it = out["sections"]["economy"][0]
    it["updates"], it["asof"] = UPDATES, "뉴욕증시 22일(현지) 마감"


@pytest.mark.parametrize("w,h", [(1180, 820), (390, 844)])
def test_flow_on_page_and_in_reader(browser, tmp_path, w, h):  # noqa: F811
    index = make_site(tmp_path, mutate=_mut)
    ctx, page, errors = open_page(browser, index, w, h)
    shown = page.evaluate("""() => [...document.querySelectorAll('#book .flow li')]
        .filter(l => getComputedStyle(l).display !== 'none').map(l => l.textContent.replace(/\s+/g, ' ').trim())""")
    st = page.evaluate("NEWS.state()")
    issue = page.evaluate("document.querySelector('#flow .flow').closest('[data-issue]').dataset.issue")
    page.evaluate(f"NEWS.openReader('{issue}')")
    in_reader = page.evaluate("document.querySelectorAll('#reader .flow li').length")
    ctx.close()
    assert not errors, errors
    assert st["overflow"] == []
    assert len(shown) == 3 and "하락 출발" in shown[0] and "Selloff" in shown[1] and "지금 이 기사" in shown[2]
    assert in_reader == 4
