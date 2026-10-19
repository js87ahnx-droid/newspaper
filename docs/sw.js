/* 오프라인 캐시 (선택 기능): 지면은 네트워크 먼저, 안 되면 마지막으로 본 지면. 정적 파일은 캐시 먼저.
   997243b45b 는 발행 때 정적 파일 해시로 바뀐다 — 지면의 정적 파일 주소에도 ?v= 로 붙어, 새로 발행하면 새 파일을 받는다 (S18) */
const VER = "997243b45b";
const CACHE = "news-" + VER;
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(["./"].concat(
    ["static/app.css", "static/app.js", "static/feedback.js", "static/vendor/page-flip/page-flip.browser.js"].map((u) => u + "?v=" + VER)))));
  self.skipWaiting();
});
self.addEventListener("activate", (e) => {   // 지난 판 캐시(옛 news-v1 포함)는 지운다
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin || e.request.method !== "GET") return; // 기사 이미지·원문은 캐시하지 않는다
  if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).then((r) => { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return r; })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("./"))));
    return;
  }
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
