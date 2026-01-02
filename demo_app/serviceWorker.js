// Service Worker for Metafor PWA
// This service worker provides offline support and caching capabilities

const CACHE_NAME = 'metafor-runtime-v1';

// Install event - activate immediately without precaching
self.addEventListener('install', (event) => {
  console.log('[Service Worker] Installing...');
  // Skip waiting to activate immediately, but don't precache
  self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
  console.log('[Service Worker] Activating...');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            console.log('[Service Worker] Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
    .then(() => self.clients.claim())
  );
});

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', (event) => {
  // Skip non-GET requests
  if (event.request.method !== 'GET') {
    return;
  }

  // Skip cross-origin requests (unless you want to cache them)
  if (!event.request.url.startsWith(self.location.origin)) {
    // For external resources, use network-first strategy
    event.respondWith(
      fetch(event.request)
        .catch(() => {
          // If network fails, try cache
          return caches.match(event.request);
        })
    );
    return;
  }

  // For same-origin requests, use network-first strategy with cache fallback
  // This prevents refresh cycles by always trying network first
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Don't cache non-successful responses or service worker itself
        if (!response || response.status !== 200 || response.type !== 'basic' || 
            event.request.url.includes('serviceWorker.js')) {
          return response;
        }

        // Clone the response for caching
        const responseToCache = response.clone();

        // Cache the fetched response asynchronously
        caches.open(CACHE_NAME)
          .then((cache) => {
            cache.put(event.request, responseToCache);
          });

        return response;
      })
      .catch(() => {
        // Network failed, try cache
        return caches.match(event.request)
          .then((cachedResponse) => {
            // If no cache and it's a document request, return index.html if available
            if (!cachedResponse && event.request.destination === 'document') {
              return caches.match('/index.html');
            }
            return cachedResponse;
          });
      })
  );
});

// Handle messages from the main thread
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  
  if (event.data && event.data.type === 'CACHE_URLS') {
    event.waitUntil(
      caches.open(CACHE_NAME).then((cache) => {
        return cache.addAll(event.data.urls);
      })
    );
  }
});
