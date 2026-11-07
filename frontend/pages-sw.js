const scope = self.registration.scope
const prefix = `nihaixia-web-${scope}-`
const cacheName = `${prefix}__BUILD_ID__`
const files = new Set(__APP_FILES__.map(path => new URL(path, scope).href))
const entry = new URL('index.html', scope).href

self.addEventListener('install', event => {
  event.waitUntil(caches.open(cacheName).then(cache => cache.addAll([...files])))
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
  event.respondWith(caches.open(cacheName).then(async cache => await cache.match(key) ?? fetch(event.request)))
})
