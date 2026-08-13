<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { dev } from '$app/environment';
  import { auth } from '$lib/auth.svelte';
  import { connection } from '$lib/realtime.svelte';
  let { children } = $props();
  let online = $state(true);
  let updateReady = $state(false);
  let serviceWorkerRegistration = $state<ServiceWorkerRegistration | null>(null);
  const publicPage = $derived(page.url.pathname === '/login');
  onMount(() => {
    online = navigator.onLine;
    const setOnline = () => online = navigator.onLine;
    addEventListener('online', setOnline); addEventListener('offline', setOnline);
    if (!auth.accessToken && !publicPage) goto('/login'); else if (auth.accessToken) connection.connect();
    if ('serviceWorker' in navigator) {
      if (dev) {
        // A development server changes frequently; an old worker would cache stale pages.
        navigator.serviceWorker.getRegistrations().then((registrations) => {
          for (const registration of registrations) registration.unregister();
        });
        caches.delete('officer-response-v1');
      } else {
        navigator.serviceWorker.register('/service-worker.js').then((registration) => {
          serviceWorkerRegistration = registration;
          updateReady = Boolean(registration.waiting && navigator.serviceWorker.controller);
          registration.addEventListener('updatefound', () => {
            const installing = registration.installing;
            installing?.addEventListener('statechange', () => {
              if (installing.state === 'installed' && navigator.serviceWorker.controller) {
                updateReady = true;
              }
            });
          });
        });
      }
    }
    return () => { removeEventListener('online', setOnline); removeEventListener('offline', setOnline); };
  });
  function signOut(){ auth.clear(); connection.close(); goto('/login'); }
  function applyUpdate() {
    const waiting = serviceWorkerRegistration?.waiting;
    if (!waiting) { updateReady = false; return; }
    let reloading = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!reloading) { reloading = true; location.reload(); }
    });
    waiting.postMessage({ type: 'SKIP_WAITING' });
  }
</script>

<svelte:head><title>Sign Response</title><meta name="description" content="Officer response for deaf and hard-of-hearing people" /></svelte:head>
{#if !online}<div class="connection-banner offline">Offline — showing previously loaded information</div>{:else if auth.accessToken && !connection.connected}<div class="connection-banner">Connection lost. Trying to reconnect…</div>{/if}
{#if updateReady}<button class="update-banner" onclick={applyUpdate}>A newer version is ready. Tap to update.</button>{/if}
{#if publicPage}
  {@render children()}
{:else}
  <div class="app-shell">
    <aside>
      <a class="brand" href="/dashboard"><span class="shield">+</span><span>Sign<br><strong>Response</strong></span></a>
      <nav aria-label="Main navigation">
        <a class:active={page.url.pathname === '/dashboard'} href="/dashboard">Overview</a>
        <a class:active={page.url.pathname.startsWith('/reports')} href="/reports">Reports</a>
        <a class:active={page.url.pathname === '/map'} href="/map">Map</a>
        <a class:active={page.url.pathname === '/history'} href="/history">History</a>
        <a class:active={page.url.pathname === '/profile'} href="/profile">Profile</a>
      </nav>
      <button class="signout" onclick={signOut}>Sign out</button>
    </aside>
    <main>{@render children()}</main>
    <nav class="mobile-nav" aria-label="Main navigation"><a href="/dashboard">Overview</a><a href="/reports">Reports</a><a href="/map">Map</a><a href="/history">History</a></nav>
  </div>
{/if}
