// 편집 리뷰 저장 시험 (S38a) — reviews.js 를 가짜 KV 로 직접 부른다
// 실행: cd worker && node --test test/
import { test } from "node:test";
import assert from "node:assert/strict";
import { handleReviews, validateReviews, MAX_ITEMS } from "../src/reviews.js";

const json = (body, status) => ({ status, body });
function kv() {
  const m = new Map(), ttl = new Map();
  return {
    get: async (k) => (m.has(k) ? m.get(k) : null),
    put: async (k, v, o) => { m.set(k, v); if (o) ttl.set(k, o.expirationTtl); },
    list: async ({ prefix }) => ({ keys: [...m.keys()].filter((k) => k.startsWith(prefix)).sort().map((name) => ({ name })), list_complete: true }),
    m, ttl,
  };
}
const req = (method, body) => ({ method, text: async () => (typeof body === "string" ? body : JSON.stringify(body)) });
const U = (q) => new URL("https://w.test/reviews" + (q || ""));
const S = { attention: 0.9, importance: 0.8, headline: 0.7, continuity: 0.33333, interest: 0.4, final: 0.78 };
const R = { verdict: "down", memo: " 국내 영향 없음 ", topic: "international", section: "front", rank: 2, scores: S };
const GOOD = { v: 1, edition: "2026-11-03", items: { abc123: R, "x_9-": { ...R, verdict: "ok", memo: "" } }, updated: "2026-11-03T01:00:00Z" };

test("저장 뒤 목록으로 받기 (메모 다듬기, 점수 넷째 자리, 60일)", async () => {
  const env = { PREFS: kv() };
  const w = await handleReviews(req("POST", GOOD), env, json, "/reviews", U());
  assert.deepEqual([w.status, w.body.count], [200, 2]);
  await handleReviews(req("POST", { ...GOOD, edition: "2026-10-20" }), env, json, "/reviews", U());
  assert.equal(env.PREFS.ttl.get("reviews:2026-11-03"), 60 * 86400);
  const r = await handleReviews(req("GET"), env, json, "/reviews", U("?from=2026-11-01"));
  assert.equal(r.body.reviews.length, 1);
  const rec = r.body.reviews[0];
  assert.equal(rec.items.abc123.memo, "국내 영향 없음");
  assert.equal(rec.items.abc123.scores.continuity, 0.3333);
  assert.ok(!("memo" in rec.items["x_9-"]));
  assert.equal(r.body.reset, null);
  const all = await handleReviews(req("GET"), env, json, "/reviews", U());
  assert.deepEqual(all.body.reviews.map((x) => x.edition), ["2026-10-20", "2026-11-03"]);
});

test("되돌리기 요청은 시각을 남긴다", async () => {
  const env = { PREFS: kv() };
  const w = await handleReviews(req("POST"), env, json, "/reviews/reset", U());
  assert.equal(w.status, 200);
  const r = await handleReviews(req("GET"), env, json, "/reviews", U());
  assert.equal(r.body.reset, w.body.reset);
});

test("잘못된 값은 400, 저장 안 함", async () => {
  const env = { PREFS: kv() };
  const many = {};
  for (let i = 0; i <= MAX_ITEMS; i++) many["a" + i] = R;
  const bad = [
    "x", { ...GOOD, v: 2 }, { ...GOOD, edition: "11/3" }, { ...GOOD, items: [] }, { ...GOOD, items: many },
    { ...GOOD, items: { "a b": R } }, { ...GOOD, items: { a: { ...R, verdict: "great" } } }, { ...GOOD, items: { a: { ...R, memo: "가".repeat(201) } } },
    { ...GOOD, items: { a: { ...R, topic: "nope" } } }, { ...GOOD, items: { a: { ...R, rank: 1.5 } } },
    { ...GOOD, items: { a: { ...R, scores: { ...S, final: 2 } } } }, { ...GOOD, items: { a: { ...R, scores: { ...S, headline: undefined } } } },
    { ...GOOD, updated: "어제" },
  ];
  for (const b of bad) assert.equal((await handleReviews(req("POST", b), env, json, "/reviews", U())).status, 400, JSON.stringify(b).slice(0, 60));
  assert.equal(env.PREFS.m.size, 0);
  assert.equal((await handleReviews(req("GET"), env, json, "/reviews", U("?from=어제"))).status, 400);
});

test("본문 64KB 넘으면 413, KV 없으면 501", async () => {
  assert.equal((await handleReviews(req("POST", "x".repeat(70000)), { PREFS: kv() }, json, "/reviews", U())).status, 413);
  assert.equal((await handleReviews(req("GET"), {}, json, "/reviews", U())).status, 501);
});

test("validateReviews: 분야가 빈 글자면 받는다 (분야 모름)", () => {
  assert.ok(validateReviews({ ...GOOD, items: { a: { ...R, topic: "" } } }).record);
});
