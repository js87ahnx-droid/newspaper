// 아침 발행 시작 (S25b) — Cloudflare 예약(cron)으로 GitHub Actions daily 를 workflow_dispatch 로 부른다.
// GitHub 예약 실행은 붐빌 때 몇 시간 늦거나 빠진다 (10/19·10/20 06시대 예약이 하나도 시작 안 됨).
// 이미 발행된 호면 daily.yml 의 check 작업이 몇 초 만에 끝내므로 여러 번 불러도 된다.
// 단 daily 가 대기·진행 중이면 부르지 않는다 (S44): 같은 concurrency 그룹의 대기 실행은 하나뿐이라
// 새로 부르면 기다리던 실행이 취소되고 실패 메일이 간다 (11/11).
//
// 설정 (wrangler secret / wrangler.toml)
//   GH_TOKEN  GitHub fine-grained 토큰 — 이 저장소 하나, 권한 Actions: Read and write 만 (secret)
//   GH_REPO   "소유자/저장소" (vars)
const API = "https://api.github.com";
const ACTIVE = new Set(["queued", "in_progress", "waiting", "pending", "requested"]);

function headers(env) {
  return {
    Authorization: `Bearer ${env.GH_TOKEN}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "newspaper-reader-cron",
  };
}

// 대기·진행 중인 daily 실행 수. 목록을 못 읽으면 null (그때는 부른다 — 발행을 놓치지 않게)
export async function activeDaily(env, fetchImpl = fetch) {
  try {
    const res = await fetchImpl(`${API}/repos/${env.GH_REPO}/actions/workflows/daily.yml/runs?per_page=20`, { headers: headers(env) });
    if (res.status !== 200) return null;
    const runs = (await res.json()).workflow_runs || [];
    return runs.filter((r) => ACTIVE.has(r.status)).length;
  } catch (e) {
    return null;
  }
}

export async function dispatchDaily(env, fetchImpl = fetch) {
  if (!env.GH_TOKEN || !env.GH_REPO) return { ok: false, reason: "GH_TOKEN·GH_REPO 없음" };
  const busy = await activeDaily(env, fetchImpl);
  if (busy) return { ok: true, skipped: true, busy };
  const res = await fetchImpl(`${API}/repos/${env.GH_REPO}/actions/workflows/daily.yml/dispatches`, {
    method: "POST",
    headers: { ...headers(env), "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main" }),   // 입력 없음 = 가장 최근에 닫힌 시간창, 발행됐으면 건너뜀
  });
  return { ok: res.status === 204, status: res.status };
}
