// 한국어 번역 (S17b): 원문 창에서 한국 매체가 아닌 기사를 그 자리에서 번역한다 — Cloudflare Workers AI (무료 할당량), 저장 안 함
//
// POST /translate  {"lang": "en", "texts": ["문단", ...]}  → {"ok": true, "texts": ["번역", ...]}  (같은 개수·같은 순서)

export const MAX_TEXTS = 80;
export const MAX_CHARS = 24000;   // 요청 하나의 글자 상한 (긴 기사도 들어가게, 무료 할당량을 한 번에 다 쓰지 않게)
const LANGS = { en: "english", ja: "japanese", zh: "chinese", ar: "arabic", fr: "french", de: "german", es: "spanish", ru: "russian" };
const M2M = "@cf/meta/m2m100-1.2b";

export function validate(body) {
  if (!body || typeof body !== "object") return "잘못된 요청";
  const { lang, texts } = body;
  if (!LANGS[lang]) return "지원하지 않는 언어";
  if (!Array.isArray(texts) || !texts.length || texts.length > MAX_TEXTS) return "문단 수 초과";
  if (!texts.every((t) => typeof t === "string")) return "잘못된 문단";
  if (texts.reduce((n, t) => n + t.length, 0) > MAX_CHARS) return "글이 너무 김";
  return null;
}

// 번역 모델 (2026-10-17 BBC 기사로 비교): Llama 4 Scout 가 자연스러운 한국어·고유명사 정확.
// Llama 3.3 70B 는 한자·일본어가 섞이고, m2m100 은 직역·오역("Crown Court"→"왕관 법원")이 많아 대신할 때만 쓴다
const LLM = "@cf/meta/llama-4-scout-17b-16e-instruct";
const GROUP_CHARS = 1500;   // 한 번에 맡기는 글자 수 — 나눠서 동시에 부른다 (7문단 한 번에 12초 → 나누면 빨라짐)
// 중국어·일본어는 한 글자가 한국어 여러 글자라 같은 글자 수에 출력이 훨씬 길다 — 작게 (S18 실측, 신화 26문단 1617자:
// 한 번에 88초, 500자씩 42초, 250자씩 14초)
const GROUP_CHARS_BY_LANG = { zh: 250, ja: 250 };
const SYSTEM = "You are a professional news translator. Translate each numbered paragraph into natural Korean newspaper style (해라체, 예: '~했다'). " +
  "Keep names, numbers, dates and quotes accurate. Translate weekday names as weekdays (Thursday → 목요일) and never turn them into calendar dates. " +
  "Convert large numbers carefully: 1 million = 100만, 800 million = 8억, 1 billion = 10억, 2.5 billion = 25억, 1 trillion = 1조; " +
  "if unsure, keep the digits with the English unit (e.g. 800 million → 8억). " +
  "Do not add, omit, merge or summarize. Never output Chinese characters or Japanese: write every Chinese or Japanese name and term in Hangul " +
  "(习近平 → 시진핑, 谋划 → 계획, 高市早苗 → 다카이치 사나에). " +
  "Output exactly one line per input paragraph, in the same order, each line starting with its number and a colon, like:\n1: 번역\n2: 번역";
const MAX_CALLS = 40;       // 요청 하나의 AI 호출 상한 (Workers 무료 하위 호출 한도 50 — Fox 54문단에서 넘침)

// 번호 줄 형식 — JSON 배열로 받으면 번역문 속 큰따옴표가 이스케이프되지 않아 자주 깨진다 (2026-10-17 실측)
export function parseNumbered(text, n) {
  const out = new Array(n).fill(null);
  for (const line of String(text || "").split(/\r?\n/)) {
    const m = /^\s*(\d+)\s*[:.)\]]\s*(.*)$/.exec(line);
    if (!m) continue;
    const k = parseInt(m[1], 10) - 1;
    if (k >= 0 && k < n && out[k] === null && m[2].trim()) out[k] = m[2].trim();
  }
  return out.every((x) => x !== null) ? out : null;
}

async function viaLLM(env, texts, model, why, budget) {
  if (budget.calls >= MAX_CALLS) return null;
  budget.calls++;
  const r = await env.AI.run(model || LLM, {
    messages: [{ role: "system", content: SYSTEM }, { role: "user", content: texts.map((t, i) => (i + 1) + ": " + t).join("\n") }],
    max_tokens: 4096,
  });
  let s = r && (r.response ?? r.result?.response);
  if (Array.isArray(s)) s = s.map((x, i) => (i + 1) + ": " + x).join("\n");
  const out = parseNumbered(s, texts.length);
  if (!out) { if (why) why.push("형식 " + String(s).slice(0, 80)); return null; }
  // 한자·가나가 섞였으면 실패로 본다 (원문에 있던 것은 괜찮다)
  const CJK = /[぀-ヿ一-鿿]/;
  if (out.some((t, i) => CJK.test(t) && !CJK.test(texts[i]))) { if (why) why.push("한자"); return null; }
  return out;
}

async function viaM2M(env, lang, text, budget) {
  if (!text.trim() || budget.calls >= MAX_CALLS) return "";
  budget.calls++;
  const r = await env.AI.run(M2M, { text, source_lang: LANGS[lang], target_lang: "korean" });
  return (r && r.translated_text) || "";
}

// 묶음 번역 → 실패하면 반으로 나눠 한 번 더 → 그래도 실패한 한 문단은 m2m100. 호출 수 상한 안에서만
async function group(env, lang, texts, why, budget, depth) {
  let got = null;
  try { got = await viaLLM(env, texts, null, why, budget); } catch (e) { if (why) why.push("오류 " + String(e).slice(0, 100)); }
  if (got) return got;
  if (texts.length > 1 && depth < 1) {
    const h = Math.ceil(texts.length / 2);
    const [a, b] = await Promise.all([group(env, lang, texts.slice(0, h), why, budget, depth + 1), group(env, lang, texts.slice(h), why, budget, depth + 1)]);
    return a.concat(b);
  }
  return Promise.all(texts.map((t) => viaM2M(env, lang, t, budget).catch(() => "")));
}

export async function translate(env, lang, texts, why) {
  // 긴 기사는 묶음이 호출 상한의 절반을 넘지 않게 키운다 (실패하면 반으로 나눠 한 번 더 부르므로)
  const total = texts.reduce((n, t) => n + t.length, 0);
  const GROUP = Math.max(GROUP_CHARS_BY_LANG[lang] || GROUP_CHARS, Math.ceil(total / (MAX_CALLS / 2)));
  const groups = [];
  let cur = [], n = 0;
  texts.forEach((t, i) => {
    if (cur.length && n + t.length > GROUP) { groups.push(cur); cur = []; n = 0; }
    cur.push(i); n += t.length;
  });
  if (cur.length) groups.push(cur);
  const budget = { calls: 0 };
  const out = new Array(texts.length).fill("");
  await Promise.all(groups.map(async (ks) => {
    const got = await group(env, lang, ks.map((k) => texts[k]), why, budget, 0);
    ks.forEach((k, j) => { out[k] = got[j] || ""; });
  }));
  return out;
}
