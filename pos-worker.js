/* Cache only the POS application shell. Never cache API responses or sessions. */
const CACHE='oimo-pos-shell-20261022-6';
const SHELL=['/pos','/styles.css','/oimo.css','/mobile-ux.css','/minimal.css','/numeric-inputs.js','/api-client.js','/company-settings.js','/receipt-printing.js','/offline-pos-core.js','/offline-pos.js','/app.js','/pos-supply-photo.js','/work-time.js','/vendor/qz-tray-2.3.0.js'];
self.addEventListener('install',event=>event.waitUntil((async()=>{const cache=await caches.open(CACHE);await Promise.all(SHELL.map(async path=>{const response=await fetch(path,{cache:'reload',credentials:'same-origin'});if(!response.ok)throw new Error('Cannot cache '+path);await cache.put(path,response);}));await self.skipWaiting();})()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{for(const name of await caches.keys())if(name.startsWith('oimo-pos-shell-')&&name!==CACHE)await caches.delete(name);await self.clients.claim();})()));
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);if(event.request.method!=='GET'||url.origin!==self.location.origin||!SHELL.includes(url.pathname))return;
 event.respondWith((async()=>{const cached=await caches.match(url.pathname,{cacheName:CACHE});return cached||fetch(event.request);})());
});
