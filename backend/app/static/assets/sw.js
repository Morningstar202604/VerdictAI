/* VerdictAI 轻量离线缓存 Service Worker
 * ------------------------------------------------------------
 * 策略：仅对下方预定义的静态资源做 cache-first；/api、/ws 一律直连，
 *       index.html 不缓存（保证发版后用户立即拿到新页面）。
 * 升级：改动任何被缓存的静态文件后，把 CACHE 版本号递增，
 *       activate 阶段会自动清掉旧缓存。
 */
const CACHE = "verdictai-v2";

const ASSETS = [
  "/static/assets/app.css",
  "/static/assets/app-core.js",
  "/static/assets/app-ui.js",
  "/static/assets/app-shell.js",
  "/static/assets/logo.svg",
  "/static/assets/icon-192.png",
  "/static/assets/icon-512.png",
  "/static/flow.html",
  "/static/assets/fonts/fonts.css",
  "/static/assets/fonts/noto-serif-sc-chinese-simplified-700-normal.woff2",
  "/static/assets/fonts/noto-serif-sc-chinese-simplified-900-normal.woff2",
  "/static/assets/fonts/noto-sans-sc-chinese-simplified-400-normal.woff2",
  "/static/assets/fonts/noto-sans-sc-chinese-simplified-700-normal.woff2",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/ws")) return;
  if (!ASSETS.includes(url.pathname)) return;

  e.respondWith(
    caches.match(req).then(
      (hit) =>
        hit ||
        fetch(req).then((resp) => {
          if (resp && resp.status === 200) {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return resp;
        })
    )
  );
});
