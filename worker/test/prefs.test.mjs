// 관심 학습값 저장 시험 (S30a) — prefs.js 를 가짜 KV 로 직접 부른다
// 실행: cd worker && node --test test/
import { test } from "node:test";
import assert from "node:assert/strict";
import { handlePrefs, validatePrefs, TOPICS } from "../src/prefs.js";

const json = (body, status) => ({ status, body });
function kv() {
  const m = new Map();
  return { get: async (k) => (m.has(k) ? m.get(k) : null), put: async (k, v) => { m.set(k, v); }, m };
}
const req = (method, body) => ({ method, text: async () => (typeof body === "string" ? body : JSON.stringify(body)) });
const GOOD = { v: 1, weights: { economy: 1.25, semis_ai: 3, incidents: 0 }, keywords: [" HBM ", "원전", "HBM"], updated: "2026-10-25T03:00:00Z" };

test("저장 뒤 읽으면 같은 값 (키워드 다듬기·겹침 빼기, 가중치 소수 둘째 자리)", async () => {
  const env = { PREFS: kv() };
  const w = await handlePrefs(req("POST", { ...GOOD, weights: { ...GOOD.weights, economy: 1.254 } }), env, json);
  assert.equal(w.status, 200);
  const r = await handlePrefs(req("GET"), env, json);
  assert.equal(r.status, 200);
  assert.deepEqual(r.body.prefs, { v: 1, weights: { economy: 1.25, semis_ai: 3, incidents: 0 }, keywords: ["HBM", "원전"], updated: "2026-10-25T03:00:00.000Z" });
});

test("아직 없으면 prefs: null", async () => {
  const r = await handlePrefs(req("GET"), { PREFS: kv() }, json);
  assert.deepEqual(r.body, { ok: true, prefs: null });
});

test("잘못된 값은 400, 저장 안 함", async () => {
  const env = { PREFS: kv() };
  const bad = [
    "not json", "[]", { ...GOOD, v: 2 }, { ...GOOD, weights: { nope: 1 } }, { ...GOOD, weights: { economy: 3.5 } },
    { ...GOOD, weights: { economy: -1 } }, { ...GOOD, weights: { economy: "1" } }, { ...GOOD, keywords: "HBM" },
    { ...GOOD, keywords: Array(31).fill("a").map((x, i) => x + i) }, { ...GOOD, keywords: ["x".repeat(31)] },
    { ...GOOD, keywords: [" "] }, { ...GOOD, updated: "어제" }, { ...GOOD, weights: null },
  ];
  for (const b of bad) {
    const r = await handlePrefs(req("POST", b), env, json);
    assert.equal(r.status, 400, JSON.stringify(b).slice(0, 60));
  }
  assert.equal(env.PREFS.m.size, 0);
});

test("본문이 4KB 넘으면 413, KV 가 없으면 501", async () => {
  assert.equal((await handlePrefs(req("POST", "x".repeat(5000)), { PREFS: kv() }, json)).status, 413);
  assert.equal((await handlePrefs(req("GET"), {}, json)).status, 501);
});

test("분야 목록은 열 개", () => {
  assert.equal(TOPICS.length, 10);
  assert.ok(validatePrefs({ ...GOOD, weights: Object.fromEntries(TOPICS.map((t) => [t, 1])) }).prefs);
});
