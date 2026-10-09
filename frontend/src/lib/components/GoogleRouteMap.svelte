<script lang="ts" module>
  let loader: Promise<void> | null = null;
  function loadGoogleMaps(key: string, onAuthFailure: () => void): Promise<void> {
    const callbacks = window as unknown as Record<string, () => void>;
    callbacks.gm_authFailure = onAuthFailure;
    loader ??= new Promise<void>((resolve, reject) => {
      callbacks.__equalGoogleMapsReady = () => resolve();
      const script = document.createElement('script');
      script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&v=weekly&loading=async&callback=__equalGoogleMapsReady`;
      script.async = true;
      script.onerror = () => { loader = null; script.remove(); reject(new Error('Google Maps failed to load')); };
      document.head.append(script);
    });
    return loader;
  }
</script>

<script lang="ts">
  import { onMount } from 'svelte';
  import { env } from '$env/dynamic/public';
  import { api } from '$lib/api/client';
  import ReportMap from '$lib/components/ReportMap.svelte';
  import type { Location, Report, RouteInfo } from '$lib/types';

  let { report, location = null }: { report: Report; location?: Location | null } = $props();
  const key = env.PUBLIC_GOOGLE_MAPS_BROWSER_KEY;
  let failed = $state(!key);
  let ready = $state(false);
  let route = $state<RouteInfo | null>(null);
  let container = $state<HTMLDivElement>();
  let map: google.maps.Map;
  let reportMarker: google.maps.Marker;
  let accuracyCircle: google.maps.Circle;
  let routeLine: google.maps.Polyline;
  let decodePath: (encoded: string) => google.maps.LatLng[];
  let lastFetch = 0;
  let lastPoint = '';
  let fitted = false;

  const eta = $derived(route ? `${Math.max(1, Math.round(route.duration_seconds / 60))} min · ${(route.distance_meters / 1000).toFixed(1)} km from ${report.office.name}` : '');

  async function refreshRoute() {
    lastFetch = Date.now();
    try { route = await api<RouteInfo>(`/officer/reports/${encodeURIComponent(report.public_id)}/route`); }
    catch { route = null; routeLine?.setPath([]); return; }
    const path = route.encoded_polyline ? decodePath(route.encoded_polyline) : [];
    routeLine.setPath(path);
    if (!fitted && path.length) {
      const bounds = new google.maps.LatLngBounds();
      path.forEach((point) => bounds.extend(point));
      map.fitBounds(bounds, 48);
      fitted = true;
    }
  }

  onMount(() => {
    if (!key) return;
    let cancelled = false;
    void (async () => {
      try {
        await loadGoogleMaps(key, () => (failed = true));
        const [{ Map, Circle, Polyline }, { Marker }, { encoding }] = await Promise.all([
          google.maps.importLibrary('maps') as Promise<google.maps.MapsLibrary>,
          google.maps.importLibrary('marker') as Promise<google.maps.MarkerLibrary>,
          google.maps.importLibrary('geometry') as Promise<google.maps.GeometryLibrary>
        ]);
        if (cancelled || !container) return;
        decodePath = encoding.decodePath;
        const office = { lat: report.office.latitude, lng: report.office.longitude };
        const point = { lat: report.initial_latitude, lng: report.initial_longitude };
        map = new Map(container, { center: point, zoom: 14, streetViewControl: false, mapTypeControl: false, fullscreenControl: false });
        new Marker({ map, position: office, title: report.office.name, icon: { path: google.maps.SymbolPath.CIRCLE, scale: 7, fillColor: '#256f83', fillOpacity: 1, strokeColor: '#ffffff', strokeWeight: 2 } });
        reportMarker = new Marker({ map, position: point, title: 'Reporter', icon: { path: google.maps.SymbolPath.CIRCLE, scale: 8, fillColor: '#d4453b', fillOpacity: 1, strokeColor: '#ffffff', strokeWeight: 3 } });
        accuracyCircle = new Circle({ map, center: point, radius: 0, strokeColor: '#d4453b', strokeOpacity: 0.5, strokeWeight: 1, fillColor: '#d4453b', fillOpacity: 0.12, clickable: false });
        routeLine = new Polyline({ map, strokeColor: '#256f83', strokeOpacity: 0.9, strokeWeight: 5 });
        ready = true;
      } catch { failed = true; }
    })();
    return () => { cancelled = true; };
  });

  $effect(() => {
    if (!ready) return;
    const latitude = location?.latitude ?? report.initial_latitude;
    const longitude = location?.longitude ?? report.initial_longitude;
    const accuracy = location ? location.accuracy : report.location_accuracy;
    const position = { lat: latitude, lng: longitude };
    reportMarker.setPosition(position);
    accuracyCircle.setCenter(position);
    accuracyCircle.setRadius(accuracy ?? 0);
    const point = `${latitude},${longitude}`;
    const since = Date.now() - lastFetch;
    if ((point !== lastPoint && since > 30000) || since > 60000) {
      lastPoint = point;
      void refreshRoute();
    }
  });
</script>

{#if failed}
  <ReportMap {report} {location} />
{:else}
  <div class="route-map">
    <div class="map" bind:this={container} aria-label="Route from the assigned office to the incident"></div>
    {#if eta}<p class="eta" aria-live="polite">{eta}</p>{/if}
  </div>
{/if}

<style>
  .route-map{position:relative;height:100%;min-height:280px}
  .map{height:100%;min-height:280px;border-radius:10px;overflow:hidden;background:#dce8ea}
  .eta{position:absolute;left:.6rem;bottom:.6rem;margin:0;padding:.35rem .65rem;border-radius:999px;background:#ffffffee;box-shadow:0 1px 4px #0003;font-size:.82rem;font-weight:700;color:#173c45}
</style>
