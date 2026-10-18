"""이슈 분야 분류 (무토큰, 규칙 기반).

근거 두 가지를 더한다.
1. 피드 섹션: 정치·경제·국제 피드에서 온 기사는 그 분야에 가산 (대부분은 'top' 피드라 정보가 없다)
2. 키워드 사전: 제목(+리드 앞부분)에 나온 한·영 키워드 수

분야 id 는 settings.TOPICS 와 같다. 해외 매체의 정치·사회·사건 기사는 한국 독자에게 '국제'이므로
한국 관련 단어가 없으면 international 로 옮긴다.
"""
from __future__ import annotations

import re
from collections import Counter

from .collect import Article
from .settings import TOPICS

KEYWORDS: dict[str, list[str]] = {
    "economy": [
        "금리", "물가", "증시", "코스피", "코스닥", "환율", "주가", "채권", "국채", "기준금리", "인플레", "소비자물가",
        "GDP", "성장률", "수출", "수입", "무역", "관세", "부동산", "집값", "아파트값", "대출", "가계부채", "연준", "한은",
        "국민연금", "펀드", "투자", "증권", "은행", "달러", "원화", "엔화", "유가", "실적", "영업이익", "순이익",
        "inflation", "stocks", "stock market", "wall street", "fed", "interest rate", "rate cut", "rate hike", "bond",
        "treasury", "tariff", "trade", "exports", "economy", "economic", "gdp", "earnings", "profit", "shares",
        "dollar", "yen", "oil prices", "investors", "bank", "imf", "recession", "jobs report", "cpi",
    ],
    "semis_ai": [
        "반도체", "HBM", "AI", "인공지능", "엔비디아", "TSMC", "삼성전자", "SK하이닉스", "하이닉스", "삼전닉스", "파운드리",
        "D램", "낸드", "칩", "데이터센터", "오픈AI", "앤트로픽", "챗GPT", "GPU",
        "semiconductor", "chip", "chips", "chipmaker", "nvidia", "artificial intelligence", "openai", "anthropic",
        "data center", "foundry", "globalfoundries", "hbm", "gpu", "coreweave",
    ],
    "politics": [
        "대통령", "국회", "여당", "야당", "與", "野", "민주당", "국민의힘", "장관", "총리", "청와대", "靑", "대통령실",
        "국정감사", "국감", "청문회", "선거", "선관위", "개헌", "탄핵", "특검", "검찰", "법무부", "중수청",
        "북한", "北", "김정은", "국방", "합참", "미사일", "외교", "한미", "한일", "한중", "안보", "주한미군", "비서실장",
        "president", "minister", "lawmakers", "national assembly", "election", "military", "security",
        "defense", "missile", "north korea", "diplomatic", "summit", "parliament", "prime minister", "resign",
        "辞表", "首相", "外相", "大臣", "国会", "選挙", "政権", "自民", "与党", "野党",
        "시장", "시정", "도지사", "지방선거", "의회", "의원", "상임위", "전체회의", "법사위", "정무위", "문체위", "국토위",
    ],
    "industry": [
        "자동차", "현대차", "배터리", "조선", "철강", "석유화학", "건설", "항공", "해운", "유통", "기업", "인수", "합병",
        "공장", "원전", "에너지", "통신", "플랫폼", "스타트업", "창업",
        "automaker", "factory", "merger", "acquisition", "startup", "airline", "shipbuilding", "steel", "battery",
    ],
    "society": [
        "교육", "학교", "대학", "수능", "노동", "노조", "파업", "복지", "의료", "병원", "의대", "저출생", "인구", "환경",
        "재판", "판결", "법원", "재심", "인권", "시민단체", "전세", "임대", "주거",
        "court", "trial", "verdict", "judge", "lawsuit", "students", "school", "union", "strike", "protest",
    ],
    "incidents": [
        "사고", "화재", "체포", "구속", "살인", "흉기", "숨져", "사망", "부상", "실종", "폭행", "사기", "피싱", "경찰",
        "참사", "추락", "붕괴", "폭발",
        "killed", "dead", "death", "police", "arrested", "shooting", "crash", "fire", "collapse", "murder", "injured",
    ],
    "entertainment_sports": [
        "배우", "가수", "아이돌", "드라마", "예능", "시사회", "컴백", "데뷔", "열애", "결혼", "♥", "OSEN",
        "야구", "축구", "농구", "배구", "골프", "올림픽", "월드컵", "선수", "우승", "MLB", "KBO", "NBA", "EPL",
        "토트넘", "손흥민", "다저스", "MK포토", "플레이오프", "포스트시즌", "트윈스", "베어스", "타이거즈", "라이온즈",
        "자이언츠", "이글스", "준PO", "[WC]", "BTS", "랜더스", "히어로즈", "다이노스", "위즈", "홈런", "투수", "타자", "폭투", "실점", "득점",
        "football", "soccer", "baseball", "basketball", "world cup", "premier league", "nba", "nfl", "mlb",
        "phillies", "dodgers", "fifa", "olympic", "coach", "championship", "playoff", "singer", "actor", "film", "movie",
        "golf", "pga", "hat-trick", "goal", "boxing", "champion", "tennis", "nhl", "hockey", "uefa", "striker", "goalkeeper", "league", "club", "tournament", "season",
    ],
    "lifestyle_culture": [
        "날씨", "기온", "여행", "맛집", "음식", "요리", "건강", "책", "출판", "전시", "공연", "영화제", "영화", "관람", "문화", "축제", "단풍",
        "weather", "travel", "food", "recipe", "books", "novel", "museum", "festival", "fashion",
    ],
    "science": [
        "과학", "우주", "위성", "로켓", "연구진", "연구팀", "논문", "기후", "지진", "누리호", "나사", "NASA",
        "space", "scientists", "researchers", "study finds", "climate", "nasa", "rocket", "satellite",
    ],
}

# 피드 섹션 → 분야 가산
SECTION_PRIOR = {
    "politics": {"politics": 2.0},
    "economy": {"economy": 2.0},
    "markets": {"economy": 2.0},
    "tech": {"semis_ai": 1.0, "industry": 1.0},
    "international": {"international": 1.5},
    "asia": {"international": 1.5},
    "china": {"international": 1.5},
}

KOREA_WORDS = re.compile(r"한국|韓|한미|한일|한중|국내|북한|北|남북|우리|korea|seoul|pyongyang|kim jong", re.I)
# 국내 기사라도 외국 일만 다루면(한국 관련 단어 없이) 국제로 본다
FOREIGN_WORDS = re.compile(
    r"미국|美|중국|中|일본|日|러시아|러|우크라|이스라엘|이란|사우디|후티|예멘|스웨덴|영국|英|프랑스|佛|독일|獨|"
    r"인도|대만|홍콩|유럽|EU|나토|NATO|유엔|트럼프|푸틴|시진핑|젤렌스키|네타냐후|교황|그린란드|알바니아|파키스탄"
)

_compiled: dict[str, list[re.Pattern]] = {}


def _patterns(topic: str) -> list[re.Pattern]:
    if topic not in _compiled:
        pats = []
        for k in KEYWORDS[topic]:
            if re.fullmatch(r"[a-z][a-z \-]*", k):  # 영어 소문자 키워드: 단어 경계, 대소문자 무시
                pats.append(re.compile(rf"\b{re.escape(k)}\b", re.I))
            else:  # 한글·약어·기호: 그대로 포함 여부 (약어는 대소문자 구분: AI, HBM)
                pats.append(re.compile(re.escape(k)))
        _compiled[topic] = pats
    return _compiled[topic]


def topic_scores(a: Article) -> Counter:
    text = f"{a.title} {a.lead[:120]}"
    scores: Counter = Counter()
    for s in a.sections:
        for t, w in SECTION_PRIOR.get(s, {}).items():
            scores[t] += w
    for t in KEYWORDS:
        hits = sum(1 for p in _patterns(t) if p.search(text))
        if hits:
            scores[t] += hits
    foreign_only = a.country == "KR" and FOREIGN_WORDS.search(text) and not KOREA_WORDS.search(text)
    if foreign_only:
        moved = sum(scores.pop(t, 0) for t in ("politics", "society", "incidents"))
        if moved:
            scores["international"] += moved
    if a.country != "KR":
        moved = sum(scores.pop(t, 0) for t in ("politics", "society", "incidents"))
        if moved and KOREA_WORDS.search(text):
            scores["politics"] += moved  # 한국·북한 관련 해외 보도는 정치·안보
        elif moved:
            scores["international"] += moved
        scores["international"] += 0.5  # 해외 매체 기사는 기본적으로 국제 쪽으로 약간
    return scores


def classify(articles: list[Article]) -> str:
    """이슈(기사 묶음)의 분야: 국내 기사가 있으면 국내 기사 근거를 두 배로 친다."""
    total: Counter = Counter()
    for a in articles:
        w = 2.0 if a.country == "KR" else 1.0
        for t, s in topic_scores(a).items():
            total[t] += w * s
    if not total:
        return "international" if all(a.country != "KR" for a in articles) else "society"
    best = max(total.items(), key=lambda kv: (kv[1], -list(TOPICS).index(kv[0])))
    return best[0]


# ---------- AI 분야 분류 (S21b) ----------
# 키워드 규칙은 한·영 단어뿐이라 일본어·중국어·프랑스어·독일어 기사와 단어가 안 걸리는 기사를 못 가른다
# (10/18호: 지면 기사 34건이 단신으로). 편집 전에 점수 상위 후보만 LLM 이 제목으로 분류한다
AI_TOPIC_RULES = """분야:
- politics: 한국 정치·행정·국회·선거·검찰 수사(정치), 북한, 한국의 외교·안보·국방
- economy: 거시경제·금리·물가·환율·증시·부동산·무역·관세·정부 경제정책 (나라 무관)
- industry: 개별 기업·산업(자동차·조선·배터리·에너지·유통·통신 등) 소식 (나라 무관)
- semis_ai: 반도체·인공지능·데이터센터·빅테크의 AI 사업 (나라 무관)
- international: 외국의 정치·외교·전쟁·분쟁·선거·시위·외국 사회 문제 (한국이 직접 당사자가 아니면)
- society: 한국 사회 — 교육·노동·복지·의료·법원 판결·인권·주거·환경
- incidents: 한국의 사건·사고·범죄·재난
- science: 과학·우주·기후 연구·의학 연구
- entertainment_sports: 연예·스포츠
- lifestyle_culture: 생활·문화·여행·음식·날씨·책·전시
외국에서 일어난 사건·사고·재난(태풍·산불·지진)·사회 문제는 international, 단 그 나라 경제·기업·반도체·과학 연구·스포츠·연예는 해당 분야
- science 는 연구·발견·우주 탐사만 — 재난 소식 자체는 science 가 아니다"""

AI_TOPIC_PROMPT = """아래는 오늘 뉴스 이슈 목록이다(번호 id, 기사 제목들 — 여러 언어). 각 이슈를 분야 하나로 분류하라.
{rules}
출력 형식: {{"topics": {{"<id>": "<분야 id>"}}}} — 분야 id 는 위 목록의 영문 그대로
{data}"""

AI_TOPIC_BATCH = 50   # S21b 평가: 100건씩이면 3번 중 2번 응답 없음


def ai_topics(rows: list[dict], ask, cache: dict) -> tuple[dict[str, str], str]:
    """rows: [{"id", "titles": [..]}] (점수 순). ask(prompt) → dict|None. cache(이슈 id → 분야)에 없는 것만 묻는다.
    돌려주는 값: (이슈 id → 분야, 상태). 틀린 분야 이름·빠진 이슈는 키워드 규칙에 맡긴다."""
    todo = [r for r in rows if r["id"] not in cache]
    sts = []

    def one(part: list[dict], retry: bool) -> None:
        lines = [f'{r["id"]}\t' + " / ".join(t[:90] for t in r["titles"][:2]) for r in part]
        data = "<data>\n" + "\n".join(lines) + "\n</data>"
        res = ask(AI_TOPIC_PROMPT.format(rules=AI_TOPIC_RULES, data=data))
        got = res.get("topics") if isinstance(res, dict) else None
        if not isinstance(got, dict):
            if retry and len(part) > 10:   # 실패하면 반으로 나눠 한 번 더 (S21b 평가: 50건 묶음도 가끔 시간 초과)
                h = len(part) // 2
                one(part[:h], False)
                one(part[h:], False)
            else:
                sts.append("응답 없음")
            return
        ids = {r["id"] for r in part}
        ok = {str(k): v for k, v in got.items() if v in TOPICS and str(k) in ids}
        cache.update(ok)
        sts.append(f"{len(ok)}/{len(part)}")

    for i in range(0, len(todo), AI_TOPIC_BATCH):
        one(todo[i:i + AI_TOPIC_BATCH], True)
    out = {r["id"]: cache[r["id"]] for r in rows if r["id"] in cache}
    return out, (", ".join(sts) if sts else "캐시")


# ---------- 관련 기사 짝짓기 (S22b) ----------
# 규칙(같은 사건 이웃·드문 단어 공유)으로는 10/18 에 1건뿐 — 언어가 다르거나 단어가 안 겹치는 후속 기사를 못 잡는다
AI_RELATED_PROMPT = """아래 H 는 오늘 지면의 본 기사, B 는 단신이다(번호, 제목 — 여러 언어).
각 단신이 어느 본 기사와 "같은 사건의 후속·다른 측면·직접 반응"이면 짝지어라. 같은 분야·같은 나라라는 것만으로는 짝짓지 마라.
같은 전쟁·분쟁·정책 안이라도 서로 다른 사건(다른 공격, 다른 표결, 다른 발표)이면 짝짓지 마라.
확실한 것만, 없으면 빈 객체. 출력 형식: {{"links": {{"B번호": "H번호"}}}}
{data}"""


def ai_related(hosts: list[dict], briefs: list[dict], ask) -> tuple[dict[str, str], str]:
    """hosts·briefs: [{"id", "title"}]. 돌려주는 값: (단신 id → 본 기사 id, 상태)."""
    if not hosts or not briefs:
        return {}, "후보 없음"
    lines = [f"H{i}\t{h['title'][:90]}" for i, h in enumerate(hosts)] + [f"B{i}\t{b['title'][:90]}" for i, b in enumerate(briefs)]
    res = ask(AI_RELATED_PROMPT.format(data="<data>\n" + "\n".join(lines) + "\n</data>"))
    got = res.get("links") if isinstance(res, dict) else None
    if not isinstance(got, dict):
        return {}, "응답 없음"
    out = {}
    for b, h in got.items():
        try:
            bi, hi = int(str(b).lstrip("Bb")), int(str(h).lstrip("Hh"))
        except ValueError:
            continue
        if 0 <= bi < len(briefs) and 0 <= hi < len(hosts):
            out[briefs[bi]["id"]] = hosts[hi]["id"]
    if not out:
        return out, "0쌍"
    # 검증 (S22b 평가: 제안만 쓰면 15쌍 중 2~3쌍이 같은 전쟁·같은 인물의 다른 사건) — 줄이기만 한다
    title = {x["id"]: x["title"] for x in hosts + briefs}
    pairs = list(out.items())
    lines = [f"P{i}\t본 기사: {title[h][:90]}\n\t단신: {title[b][:90]}" for i, (b, h) in enumerate(pairs)]
    res = ask(AI_RELATED_VERIFY.format(data="<data>\n" + "\n".join(lines) + "\n</data>"))
    keep = res.get("keep") if isinstance(res, dict) else None
    if not isinstance(keep, list):
        return {}, f"제안 {len(out)}쌍, 검증 응답 없음 — 쓰지 않음"
    ok = {f"P{i}" for i in range(len(pairs))} & {str(k).upper() for k in keep}
    final = {b: h for i, (b, h) in enumerate(pairs) if f"P{i}" in ok}
    return final, f"제안 {len(out)} → 검증 {len(final)}쌍"


AI_RELATED_VERIFY = """아래 각 쌍(P번호)에서 단신이 본 기사와 "바로 그 사건"을 다루는지 엄격히 확인하라.
같은 사건의 후속 보도·반응·다른 언어 보도·같은 사건의 다른 측면이면 남긴다.
같은 전쟁·분쟁·인물·정책을 다루더라도 다른 날의 다른 공격·다른 발언·다른 결정이면 지운다. 애매하면 지운다.
출력 형식: {{"keep": ["P0", ...]}}
{data}"""
