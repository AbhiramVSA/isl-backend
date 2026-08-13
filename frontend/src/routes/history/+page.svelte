<script lang="ts">
  import { onMount } from 'svelte';import { api } from '$lib/api/client';import ReportCard from '$lib/components/ReportCard.svelte';import type { ReportsPage } from '$lib/types';
  let result=$state<ReportsPage>({items:[],page:1,page_size:20,total:0});let loading=$state(true);let error=$state('');
  onMount(async()=>{try{result=await api('/officer/reports?status=RESOLVED&page_size=50')}catch(e){error=e instanceof Error?e.message:'History is unavailable.'}finally{loading=false}});
</script>
<div class="page-head"><div><p class="eyebrow">Previous Reports</p><h1>History</h1><p>Resolved reports handled by your office.</p></div></div>
{#if loading}<div class="skeleton"></div>{:else if error}<div class="error">{error}</div>{:else if result.items.length}<div class="list">{#each result.items as report}<ReportCard {report}/>{/each}</div>{:else}<div class="empty">No resolved reports yet.</div>{/if}
<style>.list{display:grid;gap:.8rem}</style>

