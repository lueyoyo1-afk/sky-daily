/* 光遇每日资讯 · Service Worker
   作用：缓存页面与数据，首次访问后可离线打开、可「添加到主屏」当 App 用。
   注意：Service Worker 只在 http(s) 下生效（file:// 直接双击打开时不生效，
        但页面本身已内联全量数据，双击同样是完整的）。 */
const CACHE = "sky-news-v2";
const ASSETS = [
  "./",
  "./index.html",
  "./manifest.json",
  "./data.json",
  "./guides.json",
  "./seasonGuides.json",
  "./events.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png"
];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(ASSETS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return;

  // 网络优先：联网时永远拿最新资讯，断网/离线时才回退缓存
  e.respondWith(
    fetch(e.request)
      .then(res => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then(ch => ch.put(e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
