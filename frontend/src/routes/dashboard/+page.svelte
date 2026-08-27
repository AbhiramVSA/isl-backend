<script lang="ts">
  import { onMount } from 'svelte';
  import { api, FriendlyError } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';
  import { connection } from '$lib/realtime.svelte';
  import ReportCard from '$lib/components/ReportCard.svelte';
  import SignTranscriber from '$lib/components/SignTranscriber.svelte';
  import { parseApiTime } from '$lib/time';
  import type { Report, ReportsPage } from '$lib/types';
  let reports = $state<Report[]>([]); let loading = $state(true); let error = $state(''); let notice=$state(''); let taking=$state(''); let showAll=$state(false); let scope=$state<'office'|'all'>('office'); let loadingRequest:Promise<void>|null=null;
  const visibleReports=$derived(showAll?reports:reports.slice(0,6));
  const newCount = $derived(reports.filter(r=>r.status==='NEW').length);
  const highCount = $derived(reports.filter(r=>['HIGH','CRITICAL'].includes(r.priority) && r.status!=='RESOLVED').length);
  const responding = $derived(reports.filter(r=>['RESPONDING','ARRIVED'].includes(r.status)).length);
  const resolvedToday = $derived(reports.filter(r=>r.status==='RESOLVED' && r.resolved_at && parseApiTime(r.resolved_at).toDateString()===new Date().toDateString()).length);
  async function load(){if(loadingRequest)return loadingRequest;const requestedScope=scope;loadingRequest=(async()=>{loading=true;try{const page=await api<ReportsPage>(`/officer/reports?page_size=100&scope=${requestedScope}`);reports=page.items;localStorage.setItem(`cached_reports_${requestedScope}`,JSON.stringify(reports));error=''}catch(e){const cached=localStorage.getItem(`cached_reports_${requestedScope}`);if(cached)reports=JSON.parse(cached);else error=e instanceof Error?e.message:'Reports are unavailable.'}finally{loading=false;loadingRequest=null}})();return loadingRequest}
  async function setScope(value:'office'|'all'){if(scope===value)return;if(loadingRequest)await loadingRequest;scope=value;await load()}
  async function takeReport(report: Report){taking=report.public_id;error='';notice='';try{const updated=await api<Report>(`/officer/reports/${report.public_id}/acknowledge`,{method:'POST'});reports=reports.map(item=>item.public_id===updated.public_id?updated:item);notice=`You have taken the ${updated.category} report.`}catch(e){error=e instanceof FriendlyError?e.message:'This report could not be taken.';await load()}finally{taking=''}}
  onMount(load);
  $effect(()=>{ if(connection.lastEvent?.type && connection.lastEvent.type!=='connected') load(); });
</script>
<div class="page-head"><div><p class="eyebrow">Operational overview</p><h1>Good day{auth.name ? `, ${auth.name.split(' ')[0]}` : ''}</h1><p>{scope==='all'?'Every report stored in the database.':`Reports routed to ${auth.office || 'your assigned office'}.`}</p></div><a class="button" href="/reports">Open report queue</a></div>
<SignTranscriber />
<div class="scope-row"><span>Report source</span><div class="report-toggle" role="group" aria-label="Report source"><button class:active={scope==='office'} onclick={()=>setScope('office')}>My Offices</button><button class:active={scope==='all'} onclick={()=>setScope('all')}>All Database Reports</button></div></div>
<section class="metrics" aria-label="Report summary">
  <div><span>New Reports</span><strong>{newCount}</strong></div><div class="urgent"><span>High Priority</span><strong>{highCount}</strong></div><div><span>Officers Responding</span><strong>{responding}</strong></div><div><span>Resolved Today</span><strong>{resolvedToday}</strong></div>
</section>
<div class="section-head"><div><h2>{showAll?'All Reports':'Latest Reports'}</h2><span>{connection.connected ? 'Updates active' : 'Reconnecting…'}</span></div><div class="report-toggle" role="group" aria-label="Reports shown"><button class:active={!showAll} onclick={()=>showAll=false}>Latest</button><button class:active={showAll} onclick={()=>showAll=true}>All Reports ({reports.length})</button></div></div>
{#if notice}<div class="notice" role="status">{notice}</div>{/if}{#if error}<div class="error">{error}</div>{/if}
{#if loading}<div class="grid"><div class="skeleton"></div><div class="skeleton"></div></div>{:else if visibleReports.length}<div class="grid">{#each visibleReports as report (report.public_id)}<ReportCard {report} onPick={takeReport} busy={taking===report.public_id}/>{/each}</div>{:else}<div class="empty">{scope==='all'?'There are no reports in the database.':`There are no reports routed to ${auth.office || 'your assigned office'}.`}</div>{/if}
<style>
  .scope-row{display:flex;justify-content:space-between;align-items:center;gap:1rem;background:white;border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin-bottom:1rem}.scope-row>span{font-size:.82rem;font-weight:750;color:var(--muted)}
  .report-toggle{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}.report-toggle button{border:0;background:white;color:var(--navy);padding:.55rem .8rem;font-weight:700;cursor:pointer}.report-toggle button.active{background:var(--navy);color:white}.section-head>div:first-child{display:flex;align-items:center;gap:.75rem}
  .metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin-bottom:2.2rem}.metrics div{background:white;border:1px solid var(--line);border-radius:10px;padding:1rem;display:flex;flex-direction:column-reverse;gap:.35rem;border-top:4px solid var(--blue)}.metrics .urgent{border-top-color:var(--red)}.metrics span{color:var(--muted);font-size:.88rem;font-weight:650}.metrics strong{font-size:2rem;color:#193744}.urgent strong{color:var(--red)}.section-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem}.section-head h2{margin:0;font-size:1.25rem}.section-head span{font-size:.78rem;color:var(--green);font-weight:700}.notice{background:#e2f3eb;color:#176247;border:1px solid #b9dfcf;border-radius:7px;padding:.8rem;margin-bottom:1rem;font-weight:700}.error{margin-bottom:1rem}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}@media(max-width:1000px){.metrics{grid-template-columns:repeat(2,1fr)}}@media(max-width:650px){.grid{grid-template-columns:1fr}.page-head .button{display:none}.scope-row{align-items:flex-start;flex-direction:column}.scope-row .report-toggle{width:100%}.scope-row button{flex:1}.metrics{gap:.6rem}.metrics div{padding:.8rem}.metrics strong{font-size:1.65rem}}
</style>
