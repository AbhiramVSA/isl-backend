# Officer PWA

The Svelte 5 application provides install metadata, an application-shell service worker, responsive layouts, centralized API calls, token refresh, live reconnection, a token-free MapLibre/OpenStreetMap map, and cached report/detail fallbacks.

The shell and previously opened information remain visible without a network. A persistent banner says “Offline”, cached locations become “Last known location”, and critical state changes are not queued: an officer receives confirmation from the server before the UI advances. This avoids duplicate or conflicting assignments.

Service-worker updates show an update prompt. Browser geolocation is requested only when the officer selects “Enable location” and stops with the app session.

