// 넘겨주기·쿠키 시험용 작은 Worker (S57): 가짜 fetch 로 fetchArticle 을 돌려 요청마다 실은 Cookie 를 돌려준다. 시험에서만 unstable_dev 로 띄움 — 배포 안 함
import { fetchArticle } from "../src/index.js";

// 가짜 매체: mk 는 쿠키(a=1, b=2)가 없으면 같은 주소로 되넘기고, 있으면 yna 로 넘긴다. yna 는 바로 200
function fake(log) {
  return async (url, init) => {
    const cookie = init.headers["Cookie"] || "";
    log.push({ url, cookie });
    const h = new Headers();
    if (url.includes("loop.mk.co.kr")) {   // 쿠키를 줘도 계속 되넘김
      h.set("Location", url);
      h.append("Set-Cookie", "x=1; Path=/");
      return new Response(null, { status: 302, headers: h });
    }
    if (url.startsWith("https://mk.co.kr/")) {   // apex → www 로 넘기며 쿠키 (www↔apex 같은 매체, 리뷰 N10)
      h.set("Location", url.replace("https://mk.co.kr/", "https://www.mk.co.kr/"));
      h.append("Set-Cookie", "a=1; Domain=mk.co.kr");
      h.append("Set-Cookie", "b=2");
      h.append("Set-Cookie", "z=9; Max-Age=0");
      return new Response(null, { status: 302, headers: h });
    }
    if (url.includes("mk.co.kr")) {
      if (!cookie.includes("a=1") || !cookie.includes("b=2")) {
        h.set("Location", url);
        h.append("Set-Cookie", "a=1; Path=/; HttpOnly");
        h.append("Set-Cookie", "b=2; Max-Age=60");
        return new Response(null, { status: 302, headers: h });
      }
      h.set("Location", "https://www.yna.co.kr/view/AKR1");
      return new Response(null, { status: 302, headers: h });
    }
    return new Response("<html>ok</html>", { status: 200 });
  };
}

export default {
  async fetch(req) {
    const u = new URL(req.url).searchParams.get("u");
    const log = [];
    const r = await fetchArticle(new URL(u), fake(log));
    return Response.json({ error: r.error || null, url: r.url ? r.url.toString() : null, status: r.res ? r.res.status : r.status, log });
  },
};
