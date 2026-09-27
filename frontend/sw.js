/* TripMind AI service worker.
 *
 * Purpose: make the installed app open instantly and keep working on a flaky
 * connection. Rules:
 *   - never cache /api/* (live, authenticated, must never be served stale)
 *   - navigations: network first, fall back to the cached page when offline
 *   - static assets (css/js/img): stale-while-revalidate
 *   - everything else on our origin: network, no cache
 * Bump CACHE_VERSION to ship a new build.
 */
const CACHE_VERSION = 'tripmind-v6';
const SHELL = [
  '/',
  '/index.html',
  '/login.html',
  '/register.html',
  '/portal.html',
  '/pages/planner.html',
  '/pages/dashboard.html',
  '/pages/trip.html',
  '/pages/verify.html',
  '/pages/passengers.html',
  // TripMind Partner Hub — public entry points only. The signed-in partner
  // pages are deliberately NOT precached: they are authenticated screens, and
  // they keep working through the network-first navigation rule above.
  '/tripmind-partner',
  '/tripmind-partner/login',
  '/tripmind-partner/register',
  '/tripmind-partner/css/partner.css',
  '/tripmind-partner/js/partner.js',
  '/css/style.css',
  '/css/theme.css',
  '/js/api.js',
  '/js/utils.js',
  '/js/chat.js',
  '/js/destinations.js',
  '/js/maps.js',
  '/js/pwa.js',
  '/js/ui.js',
  '/manifest.json',
  '/img/icon-192.png',
  '/img/icon-512.png',
  '/img/icon-maskable-512.png',
  '/img/apple-touch-icon.png',
  '/img/favicon-32.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION)
      // addAll fails the whole install if any single file 404s, so add
      // them one by one and tolerate the optional ones.
      .then((cache) => Promise.all(SHELL.map((url) =>
        cache.add(new Request(url, { cache: 'reload' })).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data === 'skip-waiting') self.skipWaiting();
});

function isStatic(url) {
  return /\.(css|js|png|jpe?g|gif|svg|webp|ico|woff2?)$/i.test(url.pathname);
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;   // Google Maps, fonts, etc.
  if (url.pathname.startsWith('/api/')) return;      // always live

  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then((c) => c.put(req, copy)).catch(() => null);
          return res;
        })
        .catch(() => caches.match(req)
          .then((hit) => hit || caches.match('/index.html')))
    );
    return;
  }

  if (isStatic(url)) {
    event.respondWith(
      caches.open(CACHE_VERSION).then((cache) =>
        cache.match(req).then((hit) => {
          const net = fetch(req)
            .then((res) => {
              if (res && res.status === 200 && res.type === 'basic') {
                cache.put(req, res.clone()).catch(() => null);
              }
              return res;
            })
            .catch(() => hit);
          return hit || net;
        }))
    );
  }
});
