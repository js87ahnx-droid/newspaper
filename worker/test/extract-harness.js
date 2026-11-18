// 추출기 시험용 작은 Worker (S54d): POST 로 받은 HTML 에 extract 를 돌려 결과를 돌려준다. 시험에서만 unstable_dev 로 띄움 — 배포 안 함
import { extract } from "../src/extract.js";

export default {
  async fetch(req) {
    const u = new URL(req.url);
    const html = await req.text();
    const r = await extract(new Response(html, { headers: { "content-type": "text/html; charset=utf-8" } }),
      u.searchParams.get("url") || "https://x.test/", u.searchParams.has("debug"));
    return new Response(JSON.stringify(r), { headers: { "content-type": "application/json" } });
  },
};
