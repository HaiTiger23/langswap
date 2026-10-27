const CACHE='long-studio-shell-v7';
const SHELL=['/','/assets/style.css','/assets/app.js?v=7','/manifest.webmanifest','/assets/icon.svg'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>Promise.all(SHELL.map(async path=>cache.put(path,await fetch(path,{cache:'reload'}))))).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET'||new URL(event.request.url).origin!==self.location.origin)return;
  event.respondWith(fetch(event.request).then(response=>{
    if(response.ok&&SHELL.includes(new URL(event.request.url).pathname))caches.open(CACHE).then(cache=>cache.put(event.request,response.clone()));
    return response;
  }).catch(()=>caches.match(event.request).then(cached=>cached||caches.match('/'))));
});
self.addEventListener('message',event=>{
  if(event.data?.type==='JOB_COMPLETE')self.registration.showNotification(event.data.title,{body:event.data.body,icon:'/assets/icon.svg',tag:'long-job-'+event.data.jobId,renotify:true,data:{url:'/',jobId:event.data.jobId}});
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();event.waitUntil(clients.matchAll({type:'window',includeUncontrolled:true}).then(items=>{
    const open=items[0];if(open)return open.focus();return clients.openWindow(event.notification.data?.url||'/');
  }));
});
