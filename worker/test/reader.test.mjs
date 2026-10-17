// 중계 서버 거부 규칙 시험 (S17) — 실제 Workers 런타임(wrangler 로컬)으로 띄워서 요청한다
// 실행: cd worker && node --test test/   (pytest 의 tests/test_reader_worker.py 도 이것을 부른다)
import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { unstable_dev } from "wrangler";

const KEY = "test-key-0123456789";
const ORIGIN = "https://js87ahnx-droid.github.io";
let w;

before(async () => {
  w = await unstable_dev("src/index.js", {
    vars: { READER_KEY: KEY, ALLOWED_ORIGINS: ORIGIN },
    experimental: { disableExperimentalWarning: true },
    logLevel: "none",
  });
});
after(async () => { if (w) await w.stop(); });

const get = (url, headers = {}) => w.fetch("/?url=" + encodeURIComponent(url), { headers });

test("키가 없으면 401", async () => {
  const r = await get("https://www.chosun.com/");
  assert.equal(r.status, 401);
  assert.equal((await r.json()).ok, false);
});

test("키가 다르면 401 (길이가 같아도·앞부분만 같아도)", async () => {
  for (const k of ["test-key-0123456780", "test-key", KEY + "x", ""]) {
    const r = await get("https://www.chosun.com/", { "X-Reader-Key": k });
    assert.equal(r.status, 401, k);
  }
});

test("키가 맞아도 허용목록 밖 주소는 403", async () => {
  for (const u of [
    "https://example.com/news/1",
    "https://chosun.com.evil.example/a",
    "https://evilchosun.com/a",
    "https://www.chosun.com@evil.example/a",
    "https://www.chosun.com:8443/a",
    "http://127.0.0.1/a",
    "http://169.254.169.254/latest/meta-data/",
    "http://localhost:8787/",
  ]) {
    const r = await get(u, { "X-Reader-Key": KEY });
    assert.equal(r.status, 403, u);
  }
});

test("잘못된 주소는 400", async () => {
  for (const u of ["", "not a url", "file:///etc/passwd", "javascript:alert(1)", "ftp://www.chosun.com/a"]) {
    const r = await get(u, { "X-Reader-Key": KEY });
    assert.equal(r.status, 400, u);
  }
});

test("GET 말고는 405, 응답은 저장 금지", async () => {
  const r = await w.fetch("/?url=https://www.chosun.com/", { method: "POST", headers: { "X-Reader-Key": KEY } });
  assert.equal(r.status, 405);
  assert.match(r.headers.get("Cache-Control"), /no-store/);
});

test("지면 출처에만 CORS 허용", async () => {
  const ok = await w.fetch("/", { method: "OPTIONS", headers: { Origin: ORIGIN, "Access-Control-Request-Headers": "x-reader-key" } });
  assert.equal(ok.status, 204);
  assert.equal(ok.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  const bad = await w.fetch("/", { method: "OPTIONS", headers: { Origin: "https://evil.example" } });
  assert.equal(bad.headers.get("Access-Control-Allow-Origin"), null);
  const r = await get("https://example.com/", { "X-Reader-Key": KEY, Origin: ORIGIN });
  assert.equal(r.headers.get("Access-Control-Allow-Origin"), ORIGIN);   // 거부 응답도 지면이 이유를 읽을 수 있게
});

test("번역: 키 없음 401, 잘못된 요청 400, 경로·방식이 다르면 405", async () => {
  const post = (path, body, headers = {}) => w.fetch(path, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body });
  assert.equal((await post("/translate", JSON.stringify({ lang: "en", texts: ["a"] }))).status, 401);
  const K = { "X-Reader-Key": KEY };
  for (const b of ["not json", JSON.stringify({ lang: "xx", texts: ["a"] }), JSON.stringify({ lang: "en", texts: [] }),
    JSON.stringify({ lang: "en", texts: [1] }), JSON.stringify({ lang: "en", texts: Array(81).fill("a") }),
    JSON.stringify({ lang: "en", texts: ["a".repeat(24001)] })]) {
    assert.equal((await post("/translate", b, K)).status, 400, b.slice(0, 40));
  }
  assert.equal((await post("/", JSON.stringify({ lang: "en", texts: ["a"] }), K)).status, 405);
  assert.equal((await w.fetch("/translate", { headers: K })).status, 405);
});
