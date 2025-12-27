// Universal Chess Service Worker
// Provides offline support and caching for PWA functionality

// Bump this when changing static asset structure so clients refresh cleanly.
const CACHE_NAME = 'universal-chess-v2';
const STATIC_ASSETS = [
  '/',
  '/static/css/app.css',
  '/static/js/jquery-3.4.1.min.js',
  '/static/js/chess.js',
  '/static/js/board.js',
  '/static/js/game_client.js',
  '/static/js/domarrow.js',
  '/static/js/analysis.js',
  '/static/chessboardjs/js/chessboard-1.0.0.min.js',
  '/static/chessboardjs/css/chessboard-1.0.0.css',
  '/static/manifest.json',
  '/static/icons/icon.svg'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[SW] Caching static assets');
        return cache.addAll(STATIC_ASSETS);
      })
      .then(() => self.skipWaiting())
  );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => {
            console.log('[SW] Deleting old cache:', name);
            return caches.delete(name);
          })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch event - network first, fallback to cache
self.addEventListener('fetch', (event) => {
  // Skip non-GET requests
  if (event.request.method !== 'GET') {
    return;
  }

  // Skip API calls and real-time endpoints (always fetch fresh)
  const url = new URL(event.request.url);
  if (url.pathname.startsWith('/fen') || 
      url.pathname.startsWith('/events') ||
      url.pathname.startsWith('/video') ||
      url.pathname.startsWith('/getgames') ||
      url.pathname.startsWith('/getpgn')) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Clone the response before caching
        const responseClone = response.clone();
        
        // Cache successful responses for static assets
        if (response.status === 200 && url.pathname.startsWith('/static')) {
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseClone);
          });
        }
        
        return response;
      })
      .catch(() => {
        // Network failed, try cache
        return caches.match(event.request).then((cachedResponse) => {
          if (cachedResponse) {
            return cachedResponse;
          }
          
          // Return offline page for navigation requests
          if (event.request.mode === 'navigate') {
            return caches.match('/');
          }
          
          return new Response('Offline', { status: 503 });
        });
      })
  );
});

