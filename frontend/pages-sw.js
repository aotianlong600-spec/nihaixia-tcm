const scope = self.registration.scope
const prefix = `nihaixia-web-${scope}-`
const cacheName = `${prefix}__BUILD_ID__`
const files = new Set(__APP_FILES__.map(path => new URL(path, scope).href))
const precache = new Set(__PRECACHE_FILES__.map(path => new URL(path, scope).href))
const entry = new URL('index.html', scope).href

self.addEventListener('install', event => {
  self.skipWaiting()
  event.waitUntil(caches.open(cacheName).then(cache => cache.addAll([...precache].map(url => new Request(url, { cache: 'reload' })))))
})

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys()
    await Promise.all(keys.filter(key => key.startsWith(prefix) && key !== cacheName).map(key => caches.delete(key)))
    await self.clients.claim()
  })())
})

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return
  const url = new URL(event.request.url)
  const key = url.origin + url.pathname === scope && event.request.mode === 'navigate' ? entry : url.href
  if (!files.has(key)) return
  if (!precache.has(key)) {
    // Large runtime bundles are cached on first use instead of blocking the
    // service-worker install and every subsequent app update.
    event.respondWith(fetch(event.request).then(async response => {
      if (response.ok) {
        const cache = await caches.open(cacheName)
        await cache.put(key, response.clone())
      }
      return response
    }).catch(async () => await caches.match(key)))
    return
  }
  event.respondWith(caches.open(cacheName).then(async cache => await cache.match(key) ?? fetch(event.request)))
})
