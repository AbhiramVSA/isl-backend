<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { api, download, errorMessage, qs } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';
  import { connection } from '$lib/realtime.svelte';
  import { toast } from '$lib/toast.svelte';
  import { relativeTime, localDateTime } from '$lib/time';
  import { categoryLabel, priorityLabel, statusLabel, type AdminOffice, type AdminReport, type Page, type Priority, type ReportStatus } from '$lib/types';
  import CaseActions from '$lib/components/CaseActions.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Pagination from '$lib/components/Pagination.svelte';
  import RequirePermission from '$lib/components/RequirePermission.svelte';

  const PAGE_SIZE = 25;
  let result = $state<Page<AdminReport>>({ items: [], page: 1, page_size: PAGE_SIZE, total: 0 });
  let offices = $state<AdminOffice[]>([]);
  let loading = $state(true); let error = $state(''); let exporting = $state(false);
  let search = $state(''); let status = $state<ReportStatus | ''>(''); let priority = $state<Priority | ''>(''); let officeId = $state<number | ''>('');
  let view = $state<'open' | 'unassigned' | 'all'>('open');
  let dateFrom = $state(''); let dateTo = $state(''); let sort = $state<'newest' | 'oldest' | 'priority' | 'updated'>('priority');
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  const filters = $derived({ search: search.trim(), status, priority, office_id: officeId, open_only: view !== 'all' && !status, unassigned: view === 'unassigned', date_from: dateFrom, date_to: dateTo, sort });

  async function load(page = result.page) {
    loading = true;
    try { result = await api<Page<AdminReport>>(`/admin/reports${qs({ ...filters, page, page_size: PAGE_SIZE })}`); error = ''; }
    catch (e) { error = errorMessage(e, 'Reports are unavailable.'); }
    finally { loading = false; }
  }
  const reload = () => load(1);
  function searchChanged() { clearTimeout(searchTimer); searchTimer = setTimeout(reload, 300); }
  function setView(value: typeof view) { view = value; status = ''; reload(); }
  function clearFilters() { search = ''; status = ''; priority = ''; officeId = ''; dateFrom = ''; dateTo = ''; view = 'open'; reload(); }
  const filtered = $derived(Boolean(search || status || priority || officeId || dateFrom || dateTo));

  async function exportCsv() {
    exporting = true;
    try { await download(`/admin/reports/export.csv${qs(filters)}`, 'equal-reports.csv'); toast.success('Export downloaded.'); }
    catch (e) { toast.error(errorMessage(e, 'The export failed.')); }
    finally { exporting = false; }
  }
  function replace(updated: AdminReport) { result = { ...result, items: result.items.map((item) => item.public_id === updated.public_id ? updated : item) }; }

  onMount(async () => {
    if (!auth.can('reports.view')) return;
    load(1);
    try { offices = await api<AdminOffice[]>('/admin/offices'); } catch { /* the filter just stays empty */ }
  });
  $effect(() => { if (connection.lastEvent?.type && connection.lastEvent.type !== 'connected') untrack(() => load()); });
</script>

<svelte:head><title>Case management · Equal</title></svelte:head>
<RequirePermission permission="reports.view">
  <div class="page-head">
    <div><p class="eyebrow">Management</p><h1>Case management</h1><p>Search, assign and close reports across {auth.profile?.global_scope ? 'every office' : (auth.office ?? 'your offices')}.</p></div>
    {#if auth.can('reports.export')}<div class="page-actions"><button class="button secondary" onclick={exportCsv} disabled={exporting}><Icon name="download" size={16} />{exporting ? 'Preparing…' : 'Export CSV'}</button></div>{/if}
  </div>

  <div class="tabs" role="tablist" aria-label="Report view">
    <button role="tab" aria-selected={view === 'open'} class:active={view === 'open'} onclick={() => setView('open')}>Open</button>
    <button role="tab" aria-selected={view === 'unassigned'} class:active={view === 'unassigned'} onclick={() => setView('unassigned')}>Unassigned</button>
    <button role="tab" aria-selected={view === 'all'} class:active={view === 'all'} onclick={() => setView('all')}>All reports</button>
  </div>

  <div class="toolbar" role="search">
    <label class="search"><span class="sr-only">Search reports</span><Icon name="search" size={16} /><input placeholder="Reference, category, reporter, location…" bind:value={search} oninput={searchChanged} /></label>
    <label><span class="sr-only">Status</span><select bind:value={status} onchange={reload}><option value="">Any status</option>{#each Object.entries(statusLabel) as [value, label] (value)}<option {value}>{label}</option>{/each}</select></label>
    <label><span class="sr-only">Priority</span><select bind:value={priority} onchange={reload}><option value="">Any priority</option>{#each Object.entries(priorityLabel) as [value, label] (value)}<option {value}>{label}</option>{/each}</select></label>
    {#if offices.length > 1}<label><span class="sr-only">Office</span><select bind:value={officeId} onchange={reload}><option value="">All offices</option>{#each offices as office (office.id)}<option value={office.id}>{office.name}</option>{/each}</select></label>{/if}
    <label class="date"><span>From</span><input type="date" bind:value={dateFrom} max={dateTo || undefined} onchange={reload} /></label>
    <label class="date"><span>To</span><input type="date" bind:value={dateTo} min={dateFrom || undefined} onchange={reload} /></label>
    <label><span class="sr-only">Sort</span><select bind:value={sort} onchange={reload}><option value="priority">Most urgent</option><option value="newest">Newest</option><option value="oldest">Oldest</option><option value="updated">Recently updated</option></select></label>
    {#if filtered}<button class="button ghost small" onclick={clearFilters}>Clear</button>{/if}
  </div>

  {#if error}<div class="error" role="alert">{error}</div>
  {:else if loading && !result.items.length}<div class="skeleton"></div>
  {:else if !result.items.length}<div class="empty">{view === 'unassigned' ? 'Every open report has an officer.' : 'No reports match these filters.'}</div>
  {:else}
    <div class="table-wrap" aria-busy={loading}>
      <table class="data">
        <thead><tr><th>Report</th><th>Priority</th><th>Status</th><th>Office</th><th>Officer</th><th>Received</th><th class="actions"><span class="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {#each result.items as report (report.public_id)}
            <tr>
              <td><a class="row-link primary" href={`/reports/${report.public_id}`}>{report.title || categoryLabel(report.category)}</a><span class="sub">{report.reference_code ?? report.public_id.slice(0, 8)}{report.reporter_name ? ` · ${report.reporter_name}` : ''}</span></td>
              <td><span class="pill {report.priority.toLowerCase()}">{priorityLabel[report.priority]}</span></td>
              <td><span class="pill plain status-{report.status.toLowerCase()}">{statusLabel[report.status]}</span></td>
              <td>{report.office.name}</td>
              <td>{#if report.assigned_officer}{report.assigned_officer.name}{:else}<span class="unassigned">Unassigned</span>{/if}</td>
              <td title={localDateTime(report.created_at)}>{relativeTime(report.created_at)}</td>
              <td class="actions"><CaseActions {report} compact onchange={replace} /></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <Pagination page={result.page} pageSize={result.page_size} total={result.total} onchange={load} />
  {/if}
</RequirePermission>

<style>
  .tabs{display:flex;gap:.25rem;margin-bottom:.8rem;border-bottom:1px solid var(--line)}
  .tabs button{border:0;background:transparent;padding:.6rem .9rem;font-weight:700;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}
  .tabs button.active{color:var(--navy);border-bottom-color:var(--navy)}
  .date{display:flex;align-items:center;gap:.4rem;font-size:.8rem;font-weight:700;color:var(--muted)}.date input{width:auto}
  .unassigned{color:#8a5100;font-weight:700}
  .status-new{background:#fff3d6;color:#7a4d00}.status-resolved{background:var(--green-soft);color:#176247}.status-cancelled{background:#eef0f1;color:#6b7a80}
  .status-responding,.status-arrived{background:var(--blue-soft);color:#195a71}
</style>
