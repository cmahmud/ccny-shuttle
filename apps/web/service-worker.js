const CACHE_NAME = "ccny-smart-shuttle-compact-v19";
const APP_SHELL = [
  "/", "/index.html", "/compact-v15.css", "/compact-v19.js", "/compact-core-v10.js", "/route-data-v1.js", "/arrival-ui-v3.js", "/service-calendar-v1.js",
  "/favicon.svg", "/icon.svg", "/manifest.webmanifest"
];
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin ||
      url.pathname.startsWith("/api/")) return; // GPS is always network-only.
  if (!(request.mode === "navigate" || APP_SHELL.includes(url.pathname))) return;
  event.respondWith(
    fetch(request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)));
      }
      return response;
    }).catch(async () => {
      const cached = await caches.match(request);
      return cached || (request.mode === "navigate" ? caches.match("/") : Response.error());
    })
  );
});
