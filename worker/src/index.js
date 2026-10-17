// 원문 재배열 중계 서버 (S17, D14·D16) — Cloudflare Worker
//
// GET /?url=<기사 주소>  (머리글 X-Reader-Key: <접근 키>)
//   → 그 자리에서 원문을 받아 제목·사진(원 주소)·본문 문단만 JSON 으로 돌려준다.
//   → 아무것도 저장·캐시하지 않는다 (응답에 no-store, Cloudflare 캐시도 끔, 로그에 본문 안 남김).
//
// 거부: 키가 없거나 다름(401) · 허용목록(domains.json = sources.yaml 의 site) 밖 주소(403) · 잘못된 주소(400)
// 실패: 원문 받기 실패(502) · 본문을 못 찾음(422) → 지면은 원문 링크로 넘어간다
//
// 설정 (wrangler.toml / wrangler secret)
//   READER_KEY       접근 키 (secret). 암호화된 지면 안에만 들어 있다
//   ALLOWED_ORIGINS  지면 주소 (쉼표로 여럿). 이 출처의 브라우저만 응답을 읽을 수 있다
import DOMAINS from "./domains.json";
import { extract } from "./extract.js";

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36";
const MAX_REDIRECTS = 5;
const TIMEOUT_MS = 12000;

export function allowedHost(host) {
  host = String(host || "").toLowerCase().replace(/\.$/, "");
  return DOMAINS.some((d) => host === d || host.endsWith("." + d));
}

export function checkUrl(raw) {
  let u;
  try { u = new URL(raw); } catch (e) { return { error: "잘못된 주소", status: 400 }; }
  if (u.protocol !== "https:" && u.protocol !== "http:") return { error: "http(s) 주소만", status: 400 };
  if (u.username || u.password || (u.port && u.port !== "80" && u.port !== "443")) return { error: "허용하지 않는 주소", status: 403 };
  if (!allowedHost(u.hostname)) return { error: "허용목록 밖 매체", status: 403 };
  return { url: u };
}

// 같은 길이로 비교 (키를 한 글자씩 맞혀 보는 시간 차 공격 방지)
function sameKey(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || !b) return false;
  let diff = a.length ^ b.length;
  for (let i = 0; i < b.length; i++) diff |= (a.charCodeAt(i % (a.length || 1)) || 0) ^ b.charCodeAt(i);
  return diff === 0;
}

function cors(req, env) {
  const origin = req.headers.get("Origin");
  const allowed = String(env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
  const h = { "Vary": "Origin" };
  if (origin && allowed.includes(origin)) {
    h["Access-Control-Allow-Origin"] = origin;
    h["Access-Control-Allow-Methods"] = "GET, OPTIONS";
    h["Access-Control-Allow-Headers"] = "X-Reader-Key";
    h["Access-Control-Max-Age"] = "86400";
  }
  return h;
}

function json(body, status, extra) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store, private",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      ...extra,
    },
  });
}

// 넘겨주기(redirect)를 직접 따라가며 매번 허용목록을 확인한다 (허용 매체가 다른 곳으로 넘겨도 따라가지 않게)
async function fetchArticle(url) {
  let cur = url;
  for (let i = 0; i <= MAX_REDIRECTS; i++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    let res;
    try {
      res = await fetch(cur.toString(), {
        redirect: "manual",
        signal: ctrl.signal,
        headers: { "User-Agent": UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "ko,en;q=0.8,ja;q=0.6" },
        cf: { cacheTtl: 0, cacheEverything: false },
      });
    } finally {
      clearTimeout(timer);
    }
    if (res.status >= 300 && res.status < 400 && res.headers.get("Location")) {
      const next = checkUrl(new URL(res.headers.get("Location"), cur).toString());
      if (next.error) return { error: "허용목록 밖으로 넘겨줌", status: 502 };
      cur = next.url;
      continue;
    }
    return { res, url: cur };
  }
  return { error: "넘겨주기가 너무 많음", status: 502 };
}

export default {
  async fetch(req, env) {
    const h = cors(req, env);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: h });
    if (req.method !== "GET") return json({ ok: false, reason: "GET 만" }, 405, h);
    if (!sameKey(req.headers.get("X-Reader-Key") || "", env.READER_KEY || "")) return json({ ok: false, reason: "키 없음" }, 401, h);

    const target = new URL(req.url).searchParams.get("url") || "";
    const chk = checkUrl(target);
    if (chk.error) return json({ ok: false, reason: chk.error }, chk.status, h);

    let got;
    try {
      got = await fetchArticle(chk.url);
    } catch (e) {
      return json({ ok: false, reason: e && e.name === "AbortError" ? "원문 응답 없음" : "원문 받기 실패" }, 502, h);
    }
    if (got.error) return json({ ok: false, reason: got.error }, got.status, h);
    if (got.res.status !== 200) return json({ ok: false, reason: "원문 http " + got.res.status }, 502, h);
    const type = got.res.headers.get("Content-Type") || "";
    if (type && !/html/i.test(type)) return json({ ok: false, reason: "기사 페이지가 아님" }, 422, h);

    const art = await extract(got.res, got.url.toString(), !!env.DEBUG && new URL(req.url).searchParams.has("debug"));
    if (art.debug) return json(art, 200, h);
    if (!art.ok) return json({ ok: false, reason: art.reason, url: got.url.toString() }, 422, h);
    return json(art, 200, h);
  },
};
