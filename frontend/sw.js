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
const CACHE_VERSION = 'tripmind-v8';
const SHELL = [
  '/',
  '/index.html',
  '/login.html',
  '/register.html',
  '/portal.html',
  '/pages/planner.html',
  '/pages/dashboard.html',
  '/pages/journey.html',
  '/pages/trip.html',
  '/pages/verify.html',
  '/pages/passengers.html',
  // TripMind Partner Hub \u2014 public entry points only. The signed-in partner
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
  '/js/portal.js',
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

const PARTNER_PREFIX = '/tripmind-partner';

function isPartnerPath(pathname) {
  return pathname === PARTNER_PREFIX || pathname.indexOf(PARTNER_PREFIX + '/') === 0;
}

/* Offline navigation fallback.
 *
 * This used to be a single `caches.match('/index.html')` for every navigation
 * on the origin. That meant a failed /tripmind-partner request was answered
 * with the traveller landing page - a document whose first thing on screen is
 * the full-screen brand splash. The report was "clicking For Travel Partners
 * just shows a big logo": the traveller splash, not the Partner Hub.
 *
 * The fallback is now area-aware, and a cache miss produces a real offline page
 * instead of an undefined response (which the browser renders as its own error
 * screen). */
function offlineFallback(pathname) {
  const shell = isPartnerPath(pathname) ? PARTNER_PREFIX : '/index.html';
  return caches.match(shell).then((hit) => hit || offlinePage(
    isPartnerPath(pathname)
      ? 'The TripMind Partner Hub is not available offline.'
      : 'You are offline, and this page has not been saved yet.'
  ));
}

function offlinePage(message) {
  const html = '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    + '<meta name="viewport" content="width=device-width,initial-scale=1">'
    + '<title>TripMind AI &mdash; offline</title>'
    + '<style>body{margin:0;min-height:100vh;display:grid;place-items:center;'
    + 'background:#06202b;color:#fff;font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}'
    + '.box{max-width:32rem;padding:2rem;text-align:center}'
    + 'h1{font-size:1.4rem;margin:0 0 .5rem}p{color:rgba(255,255,255,.75);margin:0 0 1.5rem}'
    + 'a{display:inline-block;background:#f0a01e;color:#06202b;font-weight:700;'
    + 'text-decoration:none;padding:.7rem 1.2rem;border-radius:99px}</style></head>'
    + '<body><div class="box"><h1>TripMind AI</h1><p>' + message + '</p>'
    + '<a href="' + PARTNER_PREFIX + '">TripMind Partner Hub</a></div></body></html>';
  return new Response(html, {
    status: 503,
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
  });
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
          .then((hit) => hit || offlineFallback(url.pathname)))
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
