const CACHE = 'equal-console-v3';
const SHELL = ['/', '/login', '/dashboard', '/reports', '/map', '/history', '/profile', '/manifest.webmanifest', '/icon.svg', '/cid-seal.png'];
// Never keep these offline: management data (staff, reporters, audit) and credentials.
const NO_STORE = ['/admin/', '/auth/'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL))));
self.addEventListener('message', event => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim())));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.pathname.includes('/api/')) {
    if (NO_STORE.some(part => url.pathname.includes(part))) return;
    event.respondWith(fetch(event.request).then(response => { const copy=response.clone(); caches.open(CACHE).then(cache=>cache.put(event.request,copy)); return response; }).catch(()=>caches.match(event.request).then(cached=>cached||new Response(JSON.stringify({detail:'Offline'}),{status:503,headers:{'Content-Type':'application/json'}}))));
    return;
  }
  event.respondWith(fetch(event.request).then(response => { caches.open(CACHE).then(cache=>cache.put(event.request,response.clone())); return response; }).catch(()=>caches.match(event.request).then(cached=>cached||caches.match('/dashboard'))));
});
