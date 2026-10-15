/* 오프라인 캐시 (선택 기능): 지면은 네트워크 먼저, 안 되면 마지막으로 본 지면. 정적 파일은 캐시 먼저. */
const CACHE = "news-v1";
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(["./", "static/app.css", "static/app.js", "static/vendor/page-flip/page-flip.browser.js"])));
  self.skipWaiting();
});
self.addEventListener("activate", (e) => { e.waitUntil(self.clients.claim()); });
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
