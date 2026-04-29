const CACHE = 'rezeptify-v2';
const SHELL = [
  '/',
  '/static/manifest.json',
  '/static/css/styles.css',
  '/static/js/app.js',
  '/static/js/api.js',
  '/static/js/utils.js',
  '/static/js/views/home.js',
  '/static/js/views/detail.js',
  '/static/js/views/form.js',
  '/static/js/views/import.js',
  '/static/js/views/buch.js',
  '/static/js/views/bot.js',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks =>
    Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Never cache API calls or uploads
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/static/uploads/')) {
    e.respondWith(fetch(e.request));
    return;
  }

  // Navigation: network first, fall back to cached shell
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).catch(() => caches.match('/'))
    );
    return;
  }

  // Static assets: cache first, network fallback with cache update
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(res => {
        if (res.ok && e.request.method === 'GET') {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      });
    })
  );
});
