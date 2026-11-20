// Vitocal Remote - Service Worker for PWA Offline Caching
const CACHE_NAME = 'vitocal-remote-v9';
const ASSETS_TO_CACHE = [
  './',
  './index.html',
  './css/styles.css',
  './js/app.js',
  './js/synoptic.js',
  './js/charts.js',
  './js/analytics.js',
  './js/commands.js',
  './js/help.js',
  './js/chart.min.js',
  './js/chartjs-adapter-date-fns.bundle.min.js',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Do not cache API endpoints or dynamic telemetry files
  if (url.pathname.includes('/api/') || url.pathname.endsWith('.jsonl') || url.searchParams.has('t')) {
    event.respondWith(fetch(event.request));
    return;
  }

  // Network first with cache fallback
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response && response.status === 200) {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseClone);
          });
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
