const C='flood-v27',SHELL=['./','./index.html','./app.js','./app.css','./reports.js','./report_rules.js','./tap_basin.js','./tap.js','./collapse.js','./manifest.json','./icon-192.png','./vendor/leaflet.js','./vendor/leaflet.css'];
self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!=C).map(x=>caches.delete(x)))).then(()=>self.clients.claim())));
// Same-origin only. Basemap tiles stay a direct browser request so the provider sees the page referrer.
self.addEventListener('fetch',e=>{
 if(e.request.method!='GET')return;
 const url=new URL(e.request.url);
 if(url.origin!==self.location.origin)return;
 e.respondWith(fetch(e.request).then(r=>{const k=r.clone();caches.open(C).then(c=>c.put(e.request,k));return r}).catch(()=>caches.match(e.request)));
});
self.addEventListener('push',e=>{
 let title='התראת שיטפון',body='';
 try{const raw=e.data?e.data.json():{};
  if(raw&&typeof raw.title==='string')title=raw.title.replace(/[\r\n]/g,' ').slice(0,120);
  if(raw&&typeof raw.body==='string')body=raw.body.replace(/[\r\n]/g,' ').slice(0,240);
 }catch(_){}
 const dest=new URL('./#alerts',self.registration.scope).href;
 const settings=new URL('./#set',self.registration.scope).href;
 e.waitUntil(self.registration.showNotification(title,{body:body,icon:'./icon-192.png',badge:'./icon-192.png',dir:'rtl',lang:'he',data:{url:dest,settings:settings},vibrate:[200,100,200],actions:[{action:'unsubscribe',title:'בטל התראות'}]}));
});
self.addEventListener('notificationclick',e=>{
 e.notification.close();
 const scope=self.registration.scope;
 const data=e.notification.data||{};
 const raw=e.action==='unsubscribe'?(data.settings||'./#set'):(data.url||'./#alerts');
 let target=new URL(e.action==='unsubscribe'?'./#set':'./#alerts',scope).href;
 try{const u=new URL(raw,scope);if(u.origin===new URL(scope).origin)target=u.href;}catch(_){}
 e.waitUntil((async()=>{
  const list=await clients.matchAll({type:'window',includeUncontrolled:true});
  for(const c of list){
   if(c.url.indexOf(new URL(scope).origin)===0){
    if(c.navigate)await c.navigate(target);
    if(c.focus)await c.focus();
    return;
   }
  }
  await clients.openWindow(target);
 })());
});
