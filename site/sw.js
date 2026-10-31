const C='flood-v3',SHELL=['./','./index.html','./app.js','./manifest.json','./icon-192.png','./vendor/leaflet.js','./vendor/leaflet.css'];
self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!=C).map(x=>caches.delete(x)))).then(()=>self.clients.claim())));
// network-first (data/*.json changes hourly), cache fallback offline
self.addEventListener('fetch',e=>{if(e.request.method!='GET')return;e.respondWith(fetch(e.request).then(r=>{const k=r.clone();caches.open(C).then(c=>c.put(e.request,k));return r}).catch(()=>caches.match(e.request)))});
self.addEventListener('push',e=>{const d=e.data?e.data.json():{title:'התראת שיטפון',body:''};e.waitUntil(self.registration.showNotification(d.title,{body:d.body,icon:'./icon-192.png',badge:'./icon-192.png',dir:'rtl',lang:'he',data:new URL(d.url||'./#alerts',self.registration.scope).href,vibrate:[200,100,200]}))});
self.addEventListener('notificationclick',e=>{e.notification.close();e.waitUntil(clients.openWindow(e.notification.data))});
