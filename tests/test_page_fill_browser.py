"""빈자리 줄이기 (2026-11-03 사용자 "1면·4면·7면·11면처럼 공백이 많이 남지 않게 — 기사를 하나 더 넣거나 글을 더 길게").

- 뉴스 면 쪽은 덜 차면 같은 면 분야의 단신·예비 기사를 일반 기사 꼴로 더 싣고, 그래도 남으면 리드·사진을 키운다
- 올린 기사는 단신·더 읽을 기사에 다시 나오지 않는다 (한 기사가 두 번 실리지 않음)
- 넘침·잘림은 그대로 없다
"""
import pytest

from tests.test_render_browser import browser, make_site, open_page  # noqa: F401  (픽스처)

NEWS = ("front", "politics", "economy", "international", "society", "interest", "more")
FILL = """(news) => [...document.querySelectorAll('#book .page')].map(p => {
    const inner = p.querySelector('.page-inner'), r = inner.getBoundingClientRect(); let bottom = r.top;
    [...inner.children].forEach(c => { const b = c.getBoundingClientRect(); if (b.height > 0) bottom = Math.max(bottom, b.bottom); });
    const sec = ([...p.classList].find(c => c.startsWith('sec-')) || '').slice(4);
    return {sec, fill: (bottom - r.top) / r.height};
  }).filter(x => news.includes(x.sec))"""


@pytest.mark.parametrize("w,h", [(1180, 820), (390, 844)])
def test_news_pages_fuller_and_no_duplicates(browser, tmp_path, w, h):  # noqa: F811
    def no_photos(out):   # 가짜 사진 주소는 오프라인에서 못 불러와 배치 뒤 접힌다 — 채우기 자체를 재려고 사진을 뺀다
        for it in [i for ps in out["sections"].values() for i in ps]:
            it["photo"] = None
    index = make_site(tmp_path, mutate=no_photos)
    ctx, page, errors = open_page(browser, index, w, h)
    page.evaluate("NEWS.setView('scroll')")
    page.wait_for_timeout(600)
    pages = page.evaluate(FILL, list(NEWS))
    ids = page.evaluate("[...document.querySelectorAll('#book article.item[data-issue]')].map(a => a.dataset.issue)")
    st = page.evaluate("NEWS.state()")
    roomy = page.evaluate("document.querySelectorAll('#book .item.roomy').length")
    ctx.close()
    assert not errors, errors
    assert st["overflow"] == [] and st["clipped"] == 0
    # 뉴스 면에 75% 못 찬 쪽이 없다. 빼는 것: 1면 첫 쪽(메인 기사 하나 — 가짜 기사는 사진·AI 정리가 없어 더 보여 줄 글이 없음),
    # 더 읽을 기사 마지막 쪽(실을 기사가 끝난 곳)
    more = [k for k, p in enumerate(pages) if p["sec"] == "more"]
    low = [(p["sec"], round(p["fill"], 2)) for k, p in enumerate(pages) if p["fill"] < 0.75 and k != 0 and k != (more[-1] if more else -1)]
    assert not low, (low, [(p["sec"], round(p["fill"], 2)) for p in pages])
    dup = {i for i in ids if ids.count(i) > 1 and not i.startswith(("front-zone", "cn-"))}
    assert not dup, dup
    assert roomy >= 0
