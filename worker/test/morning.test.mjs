// 아침 발행 시작 (S25b) — GitHub API 호출 모양만 본다 (실제 요청 없음). 실행: cd worker && node --test test/
import { test } from "node:test";
import assert from "node:assert/strict";
import { dispatchDaily } from "../src/morning.js";

test("토큰·저장소가 있으면 daily.yml 에 workflow_dispatch (ref main, 입력 없음)", async () => {
  const seen = [];
  const fake = async (url, init) => { seen.push({ url, init }); return new Response(null, { status: 204 }); };
  const r = await dispatchDaily({ GH_TOKEN: "t0k", GH_REPO: "o/r" }, fake);
  assert.deepEqual(r, { ok: true, status: 204 });
  assert.equal(seen.length, 1);
  assert.equal(seen[0].url, "https://api.github.com/repos/o/r/actions/workflows/daily.yml/dispatches");
  assert.equal(seen[0].init.method, "POST");
  assert.equal(seen[0].init.headers.Authorization, "Bearer t0k");
  assert.deepEqual(JSON.parse(seen[0].init.body), { ref: "main" });
});

test("토큰이 없으면 부르지 않음", async () => {
  let called = false;
  const r = await dispatchDaily({ GH_REPO: "o/r" }, async () => { called = true; });
  assert.equal(r.ok, false);
  assert.equal(called, false);
});

test("GitHub 가 거절하면 ok false 와 상태 코드", async () => {
  const r = await dispatchDaily({ GH_TOKEN: "x", GH_REPO: "o/r" }, async () => new Response("{}", { status: 403 }));
  assert.deepEqual(r, { ok: false, status: 403 });
});
