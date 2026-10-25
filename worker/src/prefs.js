// 관심 학습값 저장 (S30a) — 지면 설정 창의 슬라이더·키워드를 KV 한 칸에 둔다. 발행이 주마다 받아 서버 편집에 합친다(S30b)
//
// GET  /prefs  → {ok, prefs | null}
// POST /prefs  본문 {"v":1, "weights":{분야:0~3}, "keywords":[...], "updated":"ISO 시각"} → {ok, prefs}
// 키(X-Reader-Key)·출처 확인은 index.js 가 먼저 한다. KV(PREFS)가 묶여 있지 않으면 501
export const TOPICS = ["economy", "semis_ai", "politics", "international", "industry", "society",
  "entertainment_sports", "incidents", "lifestyle_culture", "science"];   // pipeline/settings.py TOPICS 와 같게 (tests/test_prefs.py)
export const MAX_BODY = 4096, MAX_W = 3, MAX_KW = 30, MAX_KW_LEN = 30;
const KEY = "prefs";

// 받은 값을 확인해 저장할 모양으로. 틀리면 {error}
export function validatePrefs(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return { error: "JSON 객체가 아님" };
  if (body.v !== 1) return { error: "v 는 1" };
  const w = body.weights;
  if (!w || typeof w !== "object" || Array.isArray(w)) return { error: "weights 없음" };
  const weights = {};
  for (const [k, v] of Object.entries(w)) {
    if (!TOPICS.includes(k)) return { error: "모르는 분야: " + String(k).slice(0, 40) };
    if (typeof v !== "number" || !Number.isFinite(v) || v < 0 || v > MAX_W) return { error: "가중치는 0~" + MAX_W + ": " + k };
    weights[k] = Math.round(v * 100) / 100;
  }
  if (!Array.isArray(body.keywords) || body.keywords.length > MAX_KW) return { error: "keywords 는 " + MAX_KW + "개까지" };
  const keywords = [];
  for (const k of body.keywords) {
    if (typeof k !== "string") return { error: "키워드는 글자" };
    const t = k.trim();
    if (!t || t.length > MAX_KW_LEN) return { error: "키워드는 1~" + MAX_KW_LEN + "자" };
    if (!keywords.includes(t)) keywords.push(t);
  }
  const u = Date.parse(body.updated);
  if (typeof body.updated !== "string" || !Number.isFinite(u)) return { error: "updated 는 ISO 시각" };
  return { prefs: { v: 1, weights, keywords, updated: new Date(u).toISOString() } };
}

// json(body, status) 은 index.js 의 응답 함수 (머리글 포함)
export async function handlePrefs(req, env, json) {
  if (!env.PREFS) return json({ ok: false, reason: "저장소 없음" }, 501);
  if (req.method === "GET") {
    const raw = await env.PREFS.get(KEY);
    let prefs = null;
    try { prefs = raw ? JSON.parse(raw) : null; } catch (e) { prefs = null; }
    return json({ ok: true, prefs }, 200);
  }
  const text = await req.text();
  if (text.length > MAX_BODY) return json({ ok: false, reason: "본문이 너무 큼" }, 413);
  let body;
  try { body = JSON.parse(text); } catch (e) { body = null; }
  const got = validatePrefs(body);
  if (got.error) return json({ ok: false, reason: got.error }, 400);
  await env.PREFS.put(KEY, JSON.stringify(got.prefs));
  return json({ ok: true, prefs: got.prefs }, 200);
}
