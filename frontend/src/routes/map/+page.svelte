<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import ReportMap from '$lib/components/ReportMap.svelte';
  import type { Report, ReportsPage } from '$lib/types';
  let reports=$state<Report[]>([]);let error=$state('');let loading=$state(true);
  onMount(async()=>{try{const data=await api<ReportsPage>('/officer/reports?page_size=100');reports=data.items.filter(r=>!['RESOLVED','CANCELLED'].includes(r.status))}catch(e){error=e instanceof Error?e.message:'Map is unavailable.'}finally{loading=false}});
</script>
<div class="page-head"><div><p class="eyebrow">Area overview</p><h1>Active Reports Map</h1><p>Critical, high, and normal priority reports for your office.</p></div></div>
{#if loading}<div class="skeleton map-loading"></div>{:else if error}<div class="error">{error}</div>{:else}<div class="map-panel"><ReportMap {reports}/></div><div class="legend"><span class="critical">Critical</span><span class="high">High</span><span class="normal">Normal</span></div>{/if}
<style>.map-panel{height:calc(100vh - 190px);min-height:500px}.map-loading{height:600px}.legend{display:flex;gap:1rem;margin-top:.7rem;font-size:.8rem;font-weight:700}.legend span:before{content:'';display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:.35rem}.critical:before{background:var(--red)}.high:before{background:var(--amber)}.normal:before{background:var(--blue)}@media(max-width:760px){.map-panel{height:calc(100vh - 230px);min-height:400px}}</style>

