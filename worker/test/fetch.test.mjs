// 넘겨주기·쿠키 시험 (S57) — 가짜 fetch 를 쓰는 시험용 Worker(fetch-harness.js)
import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { unstable_dev } from "wrangler";

let w;
before(async () => {
  w = await unstable_dev("test/fetch-harness.js", { experimental: { disableExperimentalWarning: true }, logLevel: "none" });
});
after(async () => { if (w) await w.stop(); });

const go = async (u) => (await w.fetch("/?u=" + encodeURIComponent(u))).json();

test("쿠키를 심고 같은 주소로 되넘기는 매체: 쿠키를 실어 다시 받으면 통과, 다른 매체로는 쿠키 안 보냄", async () => {
  const r = await go("https://www.mk.co.kr/news/stock/1");
  assert.equal(r.error, null);
  assert.equal(r.status, 200);
  assert.equal(r.url, "https://www.yna.co.kr/view/AKR1");
  assert.equal(r.log[0].cookie, "");
  assert.ok(r.log[1].cookie.includes("a=1") && r.log[1].cookie.includes("b=2"));
  assert.ok(!r.log[1].cookie.includes("Path") && !r.log[1].cookie.includes("HttpOnly"));
  assert.equal(r.log[2].url, "https://www.yna.co.kr/view/AKR1");
  assert.equal(r.log[2].cookie, "");
});

test("쿠키를 줘도 계속 되넘기면 넘겨주기가 너무 많음", async () => {
  const r = await go("https://loop.mk.co.kr/x");
  assert.equal(r.error, "넘겨주기가 너무 많음");
});

test("apex → www 넘겨주기에도 같은 매체라 쿠키를 싣고, Max-Age=0 쿠키는 안 실음 (리뷰 N10·N11)", async () => {
  const r = await go("https://mk.co.kr/news/1");
  assert.equal(r.status, 200);
  assert.equal(r.log[1].url, "https://www.mk.co.kr/news/1");
  assert.ok(r.log[1].cookie.includes("a=1") && r.log[1].cookie.includes("b=2") && !r.log[1].cookie.includes("z="));
  assert.equal(r.log.length, 3);   // apex → www(쿠키로 통과) → yna
});
