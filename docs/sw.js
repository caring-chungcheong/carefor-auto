// 서비스 워커 - 오프라인 지원 + 빠른 로딩 + 자동 업데이트
const CACHE_NAME = 'car-mgmt-v3-fresh';
const CACHE_FILES = [
  './',
  './index.html',
  './manifest.json',
  './icon.svg'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(c => c.addAll(CACHE_FILES)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // Apps Script(시트 API)는 캐싱 안 함 — 항상 최신 시트 데이터
  if (e.request.url.includes('script.google.com') ||
      e.request.url.includes('script.googleusercontent.com') ||
      e.request.url.includes('googleapis.com')) {
    return;
  }
  // POST 요청은 SW가 가로채지 않음
  if (e.request.method !== 'GET') return;

  const url = new URL(e.request.url);
  const isHTML = url.pathname === '/' ||
                 url.pathname.endsWith('/') ||
                 url.pathname.endsWith('/index.html') ||
                 e.request.mode === 'navigate';

  if (isHTML) {
    // index.html은 network-first — 항상 최신을 우선 시도하고, 실패 시에만 캐시
    e.respondWith(
      fetch(e.request).then(res => {
        if (res && res.status === 200) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        }
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // 나머지 정적 자원(icon, manifest 등)은 cache-first
  e.respondWith(
    caches.match(e.request).then(cached =>
      cached || fetch(e.request).then(res => {
        if (res && res.status === 200) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        }
        return res;
      }).catch(() => cached)
    )
  );
});
