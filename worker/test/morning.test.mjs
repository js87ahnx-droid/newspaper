// 아침 발행 시작 (S25b, S44) — GitHub API 호출 모양만 본다 (실제 요청 없음). 실행: cd worker && node --test test/*.test.mjs (Node 24 는 폴더를 주면 파일로 읽어 실패)
import { test } from "node:test";
import assert from "node:assert/strict";
import { dispatchDaily } from "../src/morning.js";

const RUNS = "https://api.github.com/repos/o/r/actions/runs?per_page=30";
const DISPATCH = "https://api.github.com/repos/o/r/actions/workflows/daily.yml/dispatches";

// 실행 목록 응답(runs: 상태 목록 — "상태" 는 daily, "collect:상태" 는 collect — 또는 상태 코드)과 dispatch 응답을 흉내 낸다
function fakeGitHub(runs, dispatchStatus = 204) {
  const seen = [];
  const fake = async (url, init = {}) => {
    seen.push({ url, init });
    if (url === RUNS) {
      if (typeof runs === "number") return new Response("{}", { status: runs });
      if (runs instanceof Error) throw runs;
      const rows = runs.map((r) => {
        const [wf, status] = r.includes(":") ? r.split(":") : ["daily", r];
        return { status, path: `.github/workflows/${wf}.yml` };
      });
      return new Response(JSON.stringify({ workflow_runs: rows }), { status: 200 });
    }
    return new Response(null, { status: dispatchStatus });
  };
  return { fake, seen };
}

test("대기·진행 중인 daily 가 없으면 daily.yml 에 workflow_dispatch (ref main, 입력 없음)", async () => {
  const { fake, seen } = fakeGitHub(["completed", "completed"]);
  const r = await dispatchDaily({ GH_TOKEN: "t0k", GH_REPO: "o/r" }, fake);
  assert.deepEqual(r, { ok: true, status: 204 });
  assert.deepEqual(seen.map((s) => s.url), [RUNS, DISPATCH]);
  assert.equal(seen[0].init.headers.Authorization, "Bearer t0k");
  assert.equal(seen[1].init.method, "POST");
  assert.equal(seen[1].init.headers.Authorization, "Bearer t0k");
  assert.deepEqual(JSON.parse(seen[1].init.body), { ref: "main" });
});

for (const status of ["queued", "in_progress", "waiting", "pending", "requested"]) {
  test(`daily 가 ${status} 이면 부르지 않음 — 새로 부르면 기다리던 실행이 취소된다 (11/11)`, async () => {
    const { fake, seen } = fakeGitHub(["completed", status]);
    const r = await dispatchDaily({ GH_TOKEN: "t", GH_REPO: "o/r" }, fake);
    assert.deepEqual(r, { ok: true, skipped: true, busy: 1 });
    assert.deepEqual(seen.map((s) => s.url), [RUNS]);
  });
}

test("collect 가 대기 중이면 부르지 않음 — 새로 부르면 그 collect 가 취소된다 (S46)", async () => {
  const { fake, seen } = fakeGitHub(["completed", "collect:pending"]);
  const r = await dispatchDaily({ GH_TOKEN: "t", GH_REPO: "o/r" }, fake);
  assert.deepEqual(r, { ok: true, skipped: true, busy: 1 });
  assert.deepEqual(seen.map((s) => s.url), [RUNS]);
});

test("collect 가 진행 중일 뿐이면 부른다 (daily 가 그 뒤에 대기)", async () => {
  const { fake, seen } = fakeGitHub(["completed", "collect:in_progress", "collect:completed"]);
  const r = await dispatchDaily({ GH_TOKEN: "t", GH_REPO: "o/r" }, fake);
  assert.deepEqual(r, { ok: true, status: 204 });
  assert.deepEqual(seen.map((s) => s.url), [RUNS, DISPATCH]);
});

test("실행 목록을 못 읽으면(거절·네트워크 오류) 그래도 부른다 — 발행을 놓치지 않게", async () => {
  for (const runs of [403, 500, new Error("network")]) {
    const { fake, seen } = fakeGitHub(runs);
    const r = await dispatchDaily({ GH_TOKEN: "t", GH_REPO: "o/r" }, fake);
    assert.deepEqual(r, { ok: true, status: 204 });
    assert.equal(seen.at(-1).url, DISPATCH);
  }
});

test("토큰이 없으면 부르지 않음", async () => {
  let called = false;
  const r = await dispatchDaily({ GH_REPO: "o/r" }, async () => { called = true; });
  assert.equal(r.ok, false);
  assert.equal(called, false);
});

test("GitHub 가 dispatch 를 거절하면 ok false 와 상태 코드", async () => {
  const { fake } = fakeGitHub([], 403);
  const r = await dispatchDaily({ GH_TOKEN: "x", GH_REPO: "o/r" }, fake);
  assert.deepEqual(r, { ok: false, status: 403 });
});
