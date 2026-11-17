"""S51 큐레이션 판 화면: ① 작은 사진 ⑤ 끝 쪽 합치기 ②④ 다른 각도 칸(창에서만).

기준 (project-plan.md S51d·S51f): 면 첫 기사·1면 메인이 아닌 기사 사진 너비 ≤ 쪽 너비 30%, 앞 쪽으로 합칠 수 있는데 1건만 남은
50% 미만 끝 쪽 0, 넘친 쪽 0, 다른 각도 칸은 지면에서 안 보이고 창에서 보임
"""
import pytest

from tests.test_render_browser import browser, open_page  # noqa: F401  (픽스처)
from tests.test_s49_browser import _site
from tests.test_s50_browser import KEEP, M, _b_site

SIZES = [(1180, 820), (1366, 1024), (390, 844)]
CHECK = """() => {
  const NEWS_IDS = ['front', 'politics', 'economy', 'international', 'society', 'interest', 'more'];
  const pages = [...document.querySelectorAll('#book .leaf > .page')];
  const photos = pages.flatMap(p => [...p.querySelectorAll('.page-inner > article.item:not(.sec-head):not(.top) .photo')]
    .filter(f => f.offsetHeight > 0).map(f => f.getBoundingClientRect().width / p.querySelector('.page-inner').getBoundingClientRect().width));
  const used = inn => { const r = inn.getBoundingClientRect(); let b = r.top;
    [...inn.children].forEach(c => { const q = c.getBoundingClientRect(); if (q.height > 0) b = Math.max(b, q.bottom); }); return (b - r.top) / r.height; };
  const bySec = {};
  pages.forEach(p => { const s = [...p.classList].find(c => c.startsWith('sec-')); if (s) (bySec[s.slice(4)] = bySec[s.slice(4)] || []).push(p); });
  const mergeable = [];
  ['politics', 'economy', 'international', 'society', 'interest'].forEach(id => { const ps = bySec[id] || []; if (ps.length < 2) return;
    const last = ps[ps.length - 1].querySelector('.page-inner'), prev = ps[ps.length - 2].querySelector('.page-inner');
    const arts = last.querySelectorAll(':scope > article.item');
    if (arts.length > 1 || used(last) >= 0.5) return;
    const mv = [...last.children].filter(c => c.matches('article.item, .more-list')); mv.forEach(n => prev.appendChild(n));
    if (prev.scrollHeight <= prev.clientHeight + 1) mergeable.push(id);
    mv.forEach(n => last.appendChild(n)); });
  const angOnPage = [...document.querySelectorAll('#book .ang-rows')].filter(x => x.offsetHeight > 0).length;
  return { photos, mergeable, angOnPage }; }"""


@pytest.mark.parametrize("w,h", SIZES)
def test_curated_small_photos_and_merged_tail(browser, tmp_path, w, h):
    index = _b_site(tmp_path, _site())
    ctx, page, errors = open_page(browser, index, w, h)
    st = page.evaluate("() => NEWS.state()")
    m = page.evaluate(CHECK)
    c = page.evaluate(M, KEEP)
    assert not errors and not st["overflow"] and st["clipped"] == 0, (errors, st)
    assert all(x <= 0.3 + 1e-3 for x in m["photos"]), m["photos"]
    assert not m["mergeable"], m["mergeable"]
    assert m["angOnPage"] == 0
    assert all(c["counts"][k] <= KEEP[k] for k in KEEP) and not c["listOnly"], c
    assert not any(p.startswith("sec-jonghap") for p in page.evaluate("() => [...document.querySelectorAll('#book .leaf > .page')].map(p => p.className)"))
    ctx.close()


def test_curated_angle_rows_in_reader(browser, tmp_path):
    index = _b_site(tmp_path, _site())
    ctx, page, errors = open_page(browser, index, 1180, 820)
    # 1면 메인 자세히 창 (detail 원본) 과 둘째 이슈 기사 창
    ids = page.evaluate("() => [...document.querySelectorAll('#flow article.item')].filter(a => a.querySelector('.ang-rows')).map(a => a.getAttribute('data-issue'))")
    assert ids, "다른 각도 칸이 있는 기사가 없음"
    for iid in ids:
        page.evaluate("(i) => NEWS.openReader(i)", iid)
        page.wait_for_selector("#reader:not([hidden]) .reader-body .item")
        r = page.evaluate("() => { const a = document.querySelector('#reader .ang-rows'); return a ? { h: a.offsetHeight, rows: a.querySelectorAll('.angrow').length, ang: [...a.querySelectorAll('.ang')].map(x => x.textContent) } : null; }")
        assert r and r["h"] > 0 and r["rows"] >= 1 and all(r["ang"]), (iid, r)
        page.evaluate("() => document.querySelector('[data-reader-close]').click()")
    assert not errors, errors
    ctx.close()
