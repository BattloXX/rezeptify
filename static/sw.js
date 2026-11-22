const CACHE = 'rezeptify-__ASSET_VERSION__';
const SHELL = __PRECACHE__;
const FONTS = 'rezeptify-fonts';

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(cache =>
    Promise.allSettled(SHELL.map(url => cache.add(new Request(url, { cache: 'no-store' })))))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(key => key !== CACHE && key !== FONTS).map(key => caches.delete(key)))
  ).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method === 'GET' && ['fonts.googleapis.com', 'fonts.gstatic.com'].includes(url.hostname)) {
    const refresh = caches.open(FONTS).then(async cache => {
      const response = await fetch(e.request);
      if (response.ok || response.type === 'opaque') await cache.put(e.request, response.clone());
      return response;
    });
    e.waitUntil(refresh.catch(() => {}));
    e.respondWith(caches.open(FONTS).then(async cache => await cache.match(e.request) || refresh));
    return;
  }
  if (e.request.method !== 'GET' || url.origin !== self.location.origin
      || url.pathname.startsWith('/api/') || url.pathname.startsWith('/mcp')
      || url.pathname.startsWith('/static/uploads/') || url.pathname === '/service-worker') return;

  if (e.request.mode === 'navigate') {
    e.respondWith((async () => {
      const cache = await caches.open(CACHE);
      try {
        const response = await fetch(e.request, { cache: 'no-store' });
        if (response.ok) await cache.put('/', response.clone()).catch(() => {});
        return response;
      } catch (_) {
        return await cache.match('/') || Response.error();
      }
    })());
    return;
  }

  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(e.request);
    if (cached) return cached;
    const response = await fetch(e.request);
    if (response.ok) await cache.put(e.request, response.clone()).catch(() => {});
    return response;
  })());
});
