<script lang="ts">
  import { onMount } from 'svelte';
  import type { Location, Report } from '$lib/types';
  import 'maplibre-gl/dist/maplibre-gl.css';
  let { report, location = null, reports = [] }: { report?: Report; location?: Location | null; reports?: Report[] } = $props();
  let container: HTMLDivElement;
  let map: import('maplibre-gl').Map;
  onMount(() => {
    let cancelled = false;
    void (async () => {
    const maplibre = await import('maplibre-gl');
    if (cancelled) return;
    const center: [number, number] = report ? [location?.longitude ?? report.initial_longitude, location?.latitude ?? report.initial_latitude] : reports.length ? [reports[0].initial_longitude, reports[0].initial_latitude] : [80.648, 16.506];
    map = new maplibre.Map({ container, center, zoom: report ? 14 : 11, style: { version: 8, sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap contributors' } }, layers: [{ id: 'osm', type: 'raster', source: 'osm' }] } });
    const markers = report ? [report] : reports;
    for (const item of markers) {
      const node = document.createElement('button'); node.className = `map-marker ${item.priority.toLowerCase()}`; node.setAttribute('aria-label', `${item.priority} priority: ${item.category}`);
      const popup = new maplibre.Popup({ offset: 18 }).setHTML(`<strong>${item.category}</strong><br>${item.priority === 'NORMAL' ? 'Normal' : item.priority} Priority<br><a href="/reports/${item.public_id}">View Report</a>`);
      new maplibre.Marker({ element: node }).setLngLat([item.initial_longitude, item.initial_latitude]).setPopup(popup).addTo(map);
    }
    if (report && location) new maplibre.Marker({ color: '#256f83' }).setLngLat([location.longitude, location.latitude]).addTo(map);
    })();
    return () => { cancelled = true; map?.remove(); };
  });
</script>
<div class="map" bind:this={container} aria-label="Incident location map"></div>
<style>
  .map{height:100%;min-height:280px;border-radius:10px;overflow:hidden;background:#dce8ea}
  :global(.map-marker){width:24px;height:24px;border:3px solid white;border-radius:50%;background:#2f7180;box-shadow:0 1px 5px #0008;cursor:pointer}:global(.map-marker.high){background:#df8a00}:global(.map-marker.critical){background:#d4453b}
</style>
