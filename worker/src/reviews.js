// 편집 리뷰 저장 (S38a, 20차 요청) — 설정 창 "편집 리뷰" 탭에서 기사마다 고른 평가를 호별로 KV 에 둔다.
// 발행(learn 단계)이 매일 받아 메모를 뺀 채 data/reviews 에 쓰고, 주마다 편집 가중치를 자동 조정한다 (pipeline/review.py).
//
// POST /reviews         본문 {"v":1, "edition":"YYYY-MM-DD", "items":{issue_id: 리뷰}, "updated":"ISO"} → {ok}
//                       리뷰 = {verdict: ok|up|down|drop, memo?(≤200자), topic, section, rank, scores{attention,importance,headline,continuity,interest,final}}
//                       그 호의 기록을 통째로 바꾼다 (기기가 그 호 리뷰 전체를 보낸다). 60일 뒤 KV 가 지운다
// GET  /reviews?from=YYYY-MM-DD  → {ok, reviews:[호 기록…], reset: ISO | null}
// POST /reviews/reset   자동 조정 되돌리기 요청 → {ok, reset: ISO} (다음 발행이 학습값을 지운다)
// 키(X-Reader-Key)·출처 확인은 index.js 가 먼저 한다. KV(PREFS)가 묶여 있지 않으면 501
import { TOPICS } from "./prefs.js";

export const VERDICTS = ["ok", "up", "down", "drop"];
export const SCORE_KEYS = ["attention", "importance", "headline", "continuity", "interest", "final"];
export const MAX_BODY = 65536, MAX_ITEMS = 200, MAX_MEMO = 200, TTL_DAYS = 60;
const PREFIX = "reviews:", RESET = "editing-reset";
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const ID = /^[A-Za-z0-9_-]{1,40}$/;

export function validateReviews(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return { error: "JSON 객체가 아님" };
  if (body.v !== 1) return { error: "v 는 1" };
  if (typeof body.edition !== "string" || !DAY.test(body.edition) || !Number.isFinite(Date.parse(body.edition))) return { error: "edition 은 YYYY-MM-DD" };
  const it = body.items;
  if (!it || typeof it !== "object" || Array.isArray(it)) return { error: "items 없음" };
  const ids = Object.keys(it);
  if (ids.length > MAX_ITEMS) return { error: "리뷰는 " + MAX_ITEMS + "건까지" };
  const items = {};
  for (const id of ids) {
    if (!ID.test(id)) return { error: "기사 id 형식" };
    const r = it[id];
    if (!r || typeof r !== "object" || Array.isArray(r)) return { error: "리뷰가 객체가 아님: " + id };
    if (!VERDICTS.includes(r.verdict)) return { error: "verdict 는 " + VERDICTS.join("·") };
    const out = { verdict: r.verdict };
    if (r.memo !== undefined && r.memo !== "") {
      if (typeof r.memo !== "string" || r.memo.trim().length > MAX_MEMO) return { error: "메모는 " + MAX_MEMO + "자까지" };
      if (r.memo.trim()) out.memo = r.memo.trim();
    }
    if (typeof r.topic !== "string" || !(TOPICS.includes(r.topic) || r.topic === "")) return { error: "모르는 분야" };
    if (typeof r.section !== "string" || r.section.length > 20) return { error: "section 형식" };
    if (!Number.isInteger(r.rank) || r.rank < 0 || r.rank > 500) return { error: "rank 형식" };
    const s = r.scores;
    if (!s || typeof s !== "object") return { error: "scores 없음" };
    const scores = {};
    for (const k of SCORE_KEYS) {
      if (typeof s[k] !== "number" || !Number.isFinite(s[k]) || s[k] < 0 || s[k] > 1) return { error: "점수는 0~1: " + k };
      scores[k] = Math.round(s[k] * 10000) / 10000;
    }
    Object.assign(out, { topic: r.topic, section: r.section, rank: r.rank, scores });
    items[id] = out;
  }
  const u = Date.parse(body.updated);
  if (typeof body.updated !== "string" || !Number.isFinite(u)) return { error: "updated 는 ISO 시각" };
  return { record: { v: 1, edition: body.edition, items, updated: new Date(u).toISOString() } };
}

// json(body, status) 은 index.js 의 응답 함수 (머리글 포함)
export async function handleReviews(req, env, json, path, url) {
  if (!env.PREFS) return json({ ok: false, reason: "저장소 없음" }, 501);
  if (path === "/reviews/reset") {
    const at = new Date().toISOString();
    await env.PREFS.put(RESET, at);
    return json({ ok: true, reset: at }, 200);
  }
  if (req.method === "GET") {
    const from = url.searchParams.get("from") || "";
    if (from && !DAY.test(from)) return json({ ok: false, reason: "from 은 YYYY-MM-DD" }, 400);
    const reviews = [];
    let cursor;
    do {
      const page = await env.PREFS.list({ prefix: PREFIX, cursor });
      for (const k of page.keys) {
        if (from && k.name.slice(PREFIX.length) < from) continue;
        const raw = await env.PREFS.get(k.name);
        try { if (raw) reviews.push(JSON.parse(raw)); } catch (e) { /* 깨진 칸은 건너뜀 */ }
      }
      cursor = page.list_complete ? undefined : page.cursor;
    } while (cursor);
    reviews.sort((a, b) => (a.edition < b.edition ? -1 : 1));
    return json({ ok: true, reviews, reset: (await env.PREFS.get(RESET)) || null }, 200);
  }
  const text = await req.text();
  if (text.length > MAX_BODY) return json({ ok: false, reason: "본문이 너무 큼" }, 413);
  let body;
  try { body = JSON.parse(text); } catch (e) { body = null; }
  const got = validateReviews(body);
  if (got.error) return json({ ok: false, reason: got.error }, 400);
  await env.PREFS.put(PREFIX + got.record.edition, JSON.stringify(got.record), { expirationTtl: TTL_DAYS * 86400 });
  return json({ ok: true, count: Object.keys(got.record.items).length }, 200);
}
