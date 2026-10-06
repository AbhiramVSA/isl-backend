<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage, qs } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';
  import { minutesLabel, type AdminOffice, type Analytics } from '$lib/types';
  import BarList from '$lib/components/BarList.svelte';
  import RequirePermission from '$lib/components/RequirePermission.svelte';
  import TrendChart from '$lib/components/TrendChart.svelte';

  let data = $state<Analytics | null>(null);
  let offices = $state<AdminOffice[]>([]);
  let days = $state(30); let officeId = $state<number | ''>('');
  let loading = $state(true); let error = $state(''); let showTable = $state(false);

  // Priority is a state, so it wears the reserved status colours (always with its text label).
  const priorityColor: Record<string, string> = { CRITICAL: '#c63f37', HIGH: '#d78300', NORMAL: '#2a78d6' };

  async function load() {
    loading = true;
    try { data = await api<Analytics>(`/admin/analytics${qs({ days, office_id: officeId })}`); error = ''; }
    catch (e) { error = errorMessage(e, 'Analytics are unavailable.'); }
    finally { loading = false; }
  }
  onMount(async () => {
    if (!auth.can('analytics.view')) return; load(); try { offices = await api<AdminOffice[]>('/admin/offices'); } catch { /* filter stays empty */ } });
  const resolutionRate = $derived(data && data.total ? Math.round((data.resolved / data.total) * 100) : null);
</script>

<svelte:head><title>Analytics · Equal</title></svelte:head>
<RequirePermission permission="analytics.view">
  <div class="page-head">
    <div><p class="eyebrow">Oversight</p><h1>Analytics</h1><p>Response performance for {officeId ? offices.find((o) => o.id === officeId)?.name : auth.profile?.global_scope ? 'every office' : (auth.office ?? 'your offices')}.</p></div>
  </div>
  <div class="toolbar">
    <div class="segmented" role="group" aria-label="Period">
      {#each [7, 30, 90, 365] as value (value)}<button class:on={days === value} aria-pressed={days === value} onclick={() => { days = value; load(); }}>{value === 365 ? '1 year' : `${value} days`}</button>{/each}
    </div>
    {#if offices.length > 1}<label><span class="sr-only">Office</span><select bind:value={officeId} onchange={load}><option value="">All offices</option>{#each offices as office (office.id)}<option value={office.id}>{office.name}</option>{/each}</select></label>{/if}
  </div>

  {#if error}<div class="error" role="alert">{error}</div>
  {:else if !data}<div class="stats">{#each Array(4) as _, i (i)}<div class="skeleton" style="height:96px"></div>{/each}</div>
  {:else}
    <div aria-busy={loading} class:dim={loading}>
      <section class="stats" aria-label="Headline figures">
        <div class="stat"><span>Reports received</span><strong>{data.total}</strong><small>last {data.days} days</small></div>
        <a class="stat" class:alert={data.open > 0} href="/admin/reports"><span>Open now</span><strong>{data.open}</strong><small>{data.unassigned_open} unassigned</small></a>
        <div class="stat" class:alert={data.critical_open > 0}><span>Critical & open</span><strong>{data.critical_open}</strong><small>needs attention first</small></div>
        <div class="stat"><span>Time to acknowledge</span><strong>{minutesLabel(data.avg_acknowledge_minutes)}</strong><small>average</small></div>
        <div class="stat"><span>Time to arrive</span><strong>{minutesLabel(data.avg_arrival_minutes)}</strong><small>average</small></div>
        <div class="stat"><span>Time to resolve</span><strong>{minutesLabel(data.avg_resolution_minutes)}</strong><small>{resolutionRate === null ? 'no reports' : `${resolutionRate}% resolved`}</small></div>
      </section>

      <section class="panel">
        <div class="panel-head"><h2>Reports per day</h2><button class="button ghost small" aria-pressed={showTable} onclick={() => showTable = !showTable}>{showTable ? 'Show chart' : 'Show table'}</button></div>
        {#if showTable}
          <div class="table-scroll"><table class="data"><thead><tr><th>Date</th><th class="num">Received</th><th class="num">Resolved</th></tr></thead><tbody>{#each [...data.daily].reverse() as d (d.date)}<tr><td>{new Date(`${d.date}T00:00:00`).toLocaleDateString()}</td><td class="num">{d.created}</td><td class="num">{d.resolved}</td></tr>{/each}</tbody></table></div>
        {:else}<TrendChart data={data.daily} />{/if}
      </section>

      <div class="two">
        <section class="panel"><h2>By status</h2><BarList items={data.by_status.filter((s) => s.count > 0)} /></section>
        <section class="panel"><h2>By priority</h2><BarList items={data.by_priority.map((p) => ({ ...p, color: priorityColor[p.key] }))} /></section>
        <section class="panel"><h2>Top categories</h2><BarList items={data.by_category} /></section>
        <section class="panel">
          <h2>Officer workload</h2>
          {#if data.officers.length}
            <table class="data compact"><thead><tr><th>Officer</th><th class="num">Active</th><th class="num">Resolved</th></tr></thead><tbody>{#each data.officers as o (o.officer_id)}<tr><td>{o.name}</td><td class="num" class:hot={o.active >= 3}>{o.active}</td><td class="num">{o.resolved}</td></tr>{/each}</tbody></table>
          {:else}<p class="muted">No reports were assigned in this period.</p>{/if}
        </section>
      </div>

      {#if data.offices.length > 1}
        <section class="panel">
          <h2>By office</h2>
          <div class="table-scroll"><table class="data"><thead><tr><th>Office</th><th class="num">Received</th><th class="num">Open</th><th class="num">Resolved</th><th class="num">Avg. acknowledge</th></tr></thead>
            <tbody>{#each data.offices as o (o.office_id)}<tr><td class="primary">{o.name}</td><td class="num">{o.total}</td><td class="num" class:hot={o.open > 0}>{o.open}</td><td class="num">{o.resolved}</td><td class="num">{minutesLabel(o.avg_acknowledge_minutes)}</td></tr>{/each}</tbody></table></div>
        </section>
      {/if}
    </div>
  {/if}
</RequirePermission>

<style>
  .segmented{display:flex;border:1px solid var(--line-strong);border-radius:8px;overflow:hidden}
  .segmented button{border:0;border-right:1px solid var(--line);background:var(--surface);padding:.5rem .8rem;font-weight:700;color:var(--ink-2);cursor:pointer}
  .segmented button:last-child{border-right:0}.segmented button.on{background:var(--navy);color:#fff}
  .panel{margin-bottom:1rem}.panel h2{font-size:1rem;margin:0 0 .9rem}
  .panel-head{display:flex;justify-content:space-between;align-items:center}.panel-head h2{margin:0}
  .two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.two .panel{margin-bottom:0}
  .two+.panel{margin-top:1rem}
  .compact td,.compact th{padding:.5rem .4rem}
  .hot{color:var(--red);font-weight:800}
  .table-scroll{max-height:340px;overflow:auto;border:1px solid var(--line);border-radius:8px}
  .dim{opacity:.6;transition:opacity .2s}
  @media(max-width:900px){.two{grid-template-columns:1fr}}
</style>
