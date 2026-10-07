<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import { afterNavigate, goto } from '$app/navigation';
  import { onMount, untrack } from 'svelte';
  import { dev } from '$app/environment';
  import { auth } from '$lib/auth.svelte';
  import { loadProfile } from '$lib/api/client';
  import { signOut } from '$lib/session';
  import { connection } from '$lib/realtime.svelte';
  import Icon, { type IconName } from '$lib/components/Icon.svelte';
  import Toaster from '$lib/components/Toaster.svelte';
  import type { Permission } from '$lib/types';

  let { children } = $props();
  let online = $state(true);
  let updateReady = $state(false);
  let menuOpen = $state(false);
  let serviceWorkerRegistration = $state<ServiceWorkerRegistration | null>(null);
  const publicPage = $derived(page.url.pathname === '/login');

  type NavItem = { href: string; label: string; icon: IconName; show: Permission[]; exact?: boolean };
  const groups: { label: string; items: NavItem[] }[] = [
    { label: 'Operations', items: [
      { href: '/dashboard', label: 'Overview', icon: 'overview', show: ['reports.view'], exact: true },
      { href: '/reports', label: 'Report queue', icon: 'queue', show: ['reports.view'] },
      { href: '/map', label: 'Live map', icon: 'map', show: ['reports.view'], exact: true },
      { href: '/history', label: 'History', icon: 'history', show: ['reports.view'], exact: true }
    ] },
    { label: 'Management', items: [
      { href: '/admin/reports', label: 'Case management', icon: 'cases', show: ['reports.assign', 'reports.override', 'reports.export'] },
      { href: '/admin/staff', label: 'Staff & roles', icon: 'staff', show: ['staff.view'] },
      { href: '/admin/offices', label: 'Offices', icon: 'office', show: ['staff.view', 'offices.manage'] },
      { href: '/admin/reporters', label: 'Reporters', icon: 'reporters', show: ['reporters.view'] }
    ] },
    { label: 'Oversight', items: [
      { href: '/admin/analytics', label: 'Analytics', icon: 'chart', show: ['analytics.view'] },
      { href: '/admin/audit', label: 'Audit log', icon: 'audit', show: ['audit.view'] }
    ] }
  ];
  const visibleGroups = $derived(
    groups.map((group) => ({ ...group, items: group.items.filter((item) => auth.canAny(...item.show)) })).filter((group) => group.items.length)
  );
  const mobileItems: NavItem[] = [
    { href: '/dashboard', label: 'Overview', icon: 'overview', show: [], exact: true },
    { href: '/reports', label: 'Queue', icon: 'queue', show: [] },
    { href: '/map', label: 'Map', icon: 'map', show: [], exact: true },
    { href: '/profile', label: 'Profile', icon: 'user', show: [], exact: true }
  ];
  function active(item: NavItem) {
    const path = page.url.pathname;
    return item.exact ? path === item.href : path === item.href || path.startsWith(item.href + '/');
  }
  const initials = $derived((auth.name ?? 'E').split(/\s+/).map((part) => part[0]).slice(0, 2).join('').toUpperCase());

  afterNavigate(() => { menuOpen = false; });
  // Connect live updates whenever there is a session — including right after signing in.
  $effect(() => { if (auth.accessToken && !publicPage) untrack(() => connection.connect()); });

  onMount(() => {
    online = navigator.onLine;
    const setOnline = () => online = navigator.onLine;
    addEventListener('online', setOnline); addEventListener('offline', setOnline);
    if (!auth.accessToken && !publicPage) goto('/login');
    else if (auth.accessToken) {
      // Refresh role and permissions: an admin may have changed them since sign-in.
      loadProfile().catch(() => { if (!auth.accessToken) goto('/login'); });
    }
    if ('serviceWorker' in navigator) {
      if (dev) {
        // A development server changes frequently; an old worker would cache stale pages.
        navigator.serviceWorker.getRegistrations().then((registrations) => {
          for (const registration of registrations) registration.unregister();
        });
      } else {
        navigator.serviceWorker.register('/service-worker.js').then((registration) => {
          serviceWorkerRegistration = registration;
          updateReady = Boolean(registration.waiting && navigator.serviceWorker.controller);
          registration.addEventListener('updatefound', () => {
            const installing = registration.installing;
            installing?.addEventListener('statechange', () => {
              if (installing.state === 'installed' && navigator.serviceWorker.controller) updateReady = true;
            });
          });
        });
      }
    }
    return () => { removeEventListener('online', setOnline); removeEventListener('offline', setOnline); };
  });

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

<svelte:head><title>Equal Responder Console</title><meta name="description" content="Equal — emergency response for Deaf and non-speaking people" /></svelte:head>
{#if !online}<div class="connection-banner offline" role="status">Offline — showing previously loaded information</div>{:else if auth.accessToken && connection.lost && !publicPage}<div class="connection-banner" role="status">Live updates paused. Reconnecting…</div>{/if}
{#if updateReady}<button class="update-banner" onclick={applyUpdate}>A newer version is ready. Tap to update.</button>{/if}
<Toaster />
{#if publicPage}
  {@render children()}
{:else}
  <a class="skip-link" href="#content">Skip to content</a>
  <div class="app-shell" class:menu-open={menuOpen}>
    <header class="mobile-top">
      <button class="icon-button" aria-label="Open menu" aria-expanded={menuOpen} onclick={() => menuOpen = true}><Icon name="menu" size={22} /></button>
      <a class="brand" href="/dashboard"><img class="seal" src="/cid-seal.png" alt="" width="30" height="30" /><span class="brand-text"><strong>Equal</strong></span></a>
    </header>
    {#if menuOpen}<button class="scrim" aria-label="Close menu" onclick={() => menuOpen = false}></button>{/if}
    <aside aria-label="Sidebar">
      <a class="brand" href="/dashboard" aria-label="Equal responder console, AP Police CID"><img class="seal" src="/cid-seal.png" alt="" width="40" height="40" /><span class="brand-text"><strong>Equal</strong><span>AP Police · CID</span></span></a>
      <nav aria-label="Main navigation">
        {#each visibleGroups as group (group.label)}
          <div class="nav-group">
            <span>{group.label}</span>
            {#each group.items as item (item.href)}
              <a href={item.href} class:active={active(item)} aria-current={active(item) ? 'page' : undefined}><Icon name={item.icon} />{item.label}</a>
            {/each}
          </div>
        {/each}
      </nav>
      <div class="user-card">
        <a class="who" href="/profile"><span class="avatar">{initials}</span><div><strong>{auth.name ?? 'Signed in'}</strong><small>{auth.roleLabel}{auth.office ? ` · ${auth.office}` : ''}</small></div></a>
        <button class="signout" onclick={signOut}><Icon name="logout" size={16} />Sign out</button>
      </div>
    </aside>
    <main id="content" tabindex="-1">{@render children()}</main>
    <nav class="mobile-nav" aria-label="Quick navigation">
      {#each mobileItems as item (item.href)}<a href={item.href} class:active={active(item)}><Icon name={item.icon} size={20} />{item.label}</a>{/each}
    </nav>
  </div>
{/if}
