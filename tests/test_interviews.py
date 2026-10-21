"""S27 인터뷰 — 세계 석학·사상가·구루·지도자 인터뷰 중 인사이트 있는 것을 AI 가 검토해 분석·해설 면 맨 앞에.

기준 (project-plan.md S27):
- 후보: 제목 표시([인터뷰]·Q&A·interview·インタビュー) 또는 첫 문단 "~와의 인터뷰에서"·"in an interview". 스포츠·연예 제목 제외
- AI 검토로 4건까지, 인물·한 줄 통찰. AI 가 없거나 실패하면 싣지 않는다
- 지면: 분석·해설 면 맨 앞 "인터뷰", 분석 기사와 같은 주소는 한 번만
"""
import json

from pipeline.llm import INTERVIEW_SHOW, review_interviews
from pipeline.render import build_context, render_html
from pipeline.settings import load_config, load_interests, load_sources
from pipeline.textutil import detect_interview
from tests.test_render_browser import make_site


def test_detect_interview():
    yes = [
        ('닉 보스트롬 "인간에게 지능보다 더 중요한 건 목표와 가치를 정하는 능력"',
         "닉 보스트롬 수석연구원은 14일 한국경제신문과의 화상 인터뷰에서 \"가치 있는 일을...\""),   # 2026-10-21 사용자 예시
        ("[인터뷰] 유발 하라리 \"AI는 도구가 아니라 행위자\"", ""),
        ("Yuval Noah Harari on AI and democracy", "In an interview with the FT, the historian said..."),
        ("Q&A: Mario Draghi on Europe's growth problem", ""),
        ("「AIは人類を超える」", "ヒントン氏はインタビューで語った"),
        ("알래스카 가스관공사 전 임원 “한국 750억달러 넘게 낼 수도” [인터뷰]", ""),
    ]
    no = [("Fed raises rates", "The Fed raised rates on Wednesday."), ("NBA star opens up in interview", ""),
          ("‘로코’ 배우 김영광 “생기 충전” [인터뷰]", ""), ("How to ace a job interview", "")]
    assert all(detect_interview(t, l) for t, l in yes)
    assert not any(detect_interview(t, l) for t, l in no)


CANDS = [{"id": f"i{k}", "source": s, "lang": lang, "title": t, "lead": "", "url": f"https://x.test/{k}", "lean": "중도",
          "country": "KR", "paywall": False, "published": "2026-10-21T00:00:00+00:00"}
         for k, (s, lang, t) in enumerate([("한국경제", "ko", "닉 보스트롬 인터뷰"), ("FT", "en", "Lunch with the FT: Mario Draghi"),
                                           ("매일경제", "ko", "배우 인터뷰"), ("BBC", "en", "Draghi interview")])]


def test_review_picks_caches_and_drops_on_failure():
    calls = []

    def ask(prompt):
        calls.append(prompt)
        return {"picks": [{"id": "i0", "person": "닉 보스트롬 (철학자)", "insight": "목표를 정하는 능력이 중요하다.", "ko_title": "x"},
                          {"id": "i1", "person": "마리오 드라기 (전 이탈리아 총리)", "insight": "유럽은 통합 투자가 필요하다.",
                           "ko_title": "FT와 점심: 마리오 드라기"},
                          {"id": "nope", "person": "?", "insight": "?"}]}, "ok"
    cache = {}
    out, st = review_interviews(CANDS, ask, cache)
    assert [o["id"] for o in out] == ["i0", "i1"] and out[0]["ko_title"] == "" and out[1]["ko_title"] == "FT와 점심: 마리오 드라기"
    assert "석학" in calls[0] and "연예" in calls[0] and "2/4" in st
    out2, st2 = review_interviews(CANDS, lambda p: (_ for _ in ()).throw(AssertionError("다시 부름")), cache)
    assert [o["id"] for o in out2] == ["i0", "i1"] and st2.startswith("캐시")       # 같은 후보면 캐시
    out3, st3 = review_interviews(CANDS[:2], lambda p: (None, "시간 초과 300초"), {})
    assert out3 == [] and "시간 초과" in st3                                         # 실패하면 싣지 않음
    many = review_interviews(CANDS, lambda p: ({"picks": [{"id": c["id"]} for c in CANDS] * 2}, "ok"), {})[0]
    assert len(many) == len(CANDS) <= INTERVIEW_SHOW


def test_interviews_render_first_in_analysis(tmp_path):
    box = {}

    def keep(out):
        box["ed"] = out
    make_site(tmp_path, mutate=keep)
    ed = box["ed"]
    ed["analysis"] = [dict(CANDS[3], title="Analysis: why Europe stalls")]
    ed["interviews"] = [dict(CANDS[0], person="닉 보스트롬 (철학자)", insight="목표를 정하는 능력이 중요하다."),
                        dict(CANDS[3], person="마리오 드라기 (전 총리)", insight="통합 투자.", ko_title="드라기 인터뷰")]
    cfg, interests, sources = load_config(), load_interests(), load_sources()
    sec = next(s for s in build_context(ed, cfg, interests, sources)["sections"] if s["id"] == "analysis")
    assert len(sec["interviews"]) == 2 and sec["analysis"] == []                   # 같은 주소는 인터뷰로만
    html = render_html(ed, cfg, interests, sources)
    a0 = html.index('data-section="analysis" data-title')
    body = html[a0:html.index("</section>", a0)]
    assert body.index('class="item an iv"') < body.index("닉 보스트롬 (철학자)") and "목표를 정하는 능력" in body
    assert "인터뷰</span> 마리오 드라기" in body and "드라기 인터뷰" in body
    ed.pop("interviews")
    ed["interview_candidates"] = CANDS                                             # 검토 안 된 후보는 싣지 않음
    html2 = render_html(ed, cfg, interests, sources)
    assert 'class="item an iv"' not in html2
    json.dumps(ed, ensure_ascii=False)
