// 방문요양 허브 설치 껍데기용 — PWA 설치 가능 판정에 fetch 핸들러가 필요해서 둔다.
// 캐싱은 최소로. 껍데기는 허브로 넘기는 링크뿐이라 오프라인 가치가 거의 없다.
const CACHE = 'homecare-shell-v1';
self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => { e.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  // Apps Script(허브 본체)는 절대 캐싱하지 않는다 — 항상 최신
  if (e.request.url.includes('script.google')) return;
  e.respondWith(
    fetch(e.request).then(res => {
      if (res && res.status === 200 && res.type === 'basic') {
        const c = res.clone();
        caches.open(CACHE).then(k => k.put(e.request, c));
      }
      return res;
    }).catch(() => caches.match(e.request))
  );
});
