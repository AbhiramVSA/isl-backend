<script lang="ts">
  import { onMount } from 'svelte';
  import { auth } from '$lib/auth.svelte';
  import { api, errorMessage, qs } from '$lib/api/client';
  import { localDateTime, relativeTime } from '$lib/time';
  import { roleLabel, type AuditEntry, type Page, type Role } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import Pagination from '$lib/components/Pagination.svelte';
  import RequirePermission from '$lib/components/RequirePermission.svelte';

  const PAGE_SIZE = 50;
  let result = $state<Page<AuditEntry>>({ items: [], page: 1, page_size: PAGE_SIZE, total: 0 });
  let actions = $state<string[]>([]);
  let loading = $state(true); let error = $state('');
  let search = $state(''); let action = $state(''); let targetType = $state(''); let dateFrom = $state(''); let dateTo = $state('');
  let expanded = $state<number | null>(null);
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  async function load(page = 1) {
    loading = true;
    try { result = await api<Page<AuditEntry>>(`/admin/audit${qs({ page, page_size: PAGE_SIZE, search: search.trim(), action, target_type: targetType, date_from: dateFrom, date_to: dateTo })}`); error = ''; }
    catch (e) { error = errorMessage(e, 'The audit log is unavailable.'); }
    finally { loading = false; }
  }
  onMount(async () => {
    if (!auth.can('audit.view')) return; load(); try { actions = await api<string[]>('/admin/audit/actions'); } catch { /* filter stays empty */ } });

  const humanize = (value: string) => value.toLowerCase().replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase());
  function tone(value: string) {
    if (/DISABLED|CANCEL|DEACTIVATED|RESET|OVERRIDDEN/.test(value)) return 'warn';
    if (/CREATED|ENABLED|ACTIVATED|RESOLVED/.test(value)) return 'ok';
    if (/VIEWED|EXPORTED|LOGIN/.test(value)) return 'off';
    return 'normal';
  }
  function target(entry: AuditEntry) {
    if (entry.target_type === 'REPORT' && entry.target_id) return { href: `/reports/${entry.target_id}`, label: `Report ${entry.target_id.slice(0, 8)}` };
    return { href: null, label: `${humanize(entry.target_type)}${entry.target_id ? ` #${entry.target_id}` : ''}` };
  }
  const details = (entry: AuditEntry) => Object.entries(entry.metadata).filter(([, value]) => value !== null && value !== '' && !(Array.isArray(value) && !value.length));
</script>

<svelte:head><title>Audit log · Equal</title></svelte:head>
<RequirePermission permission="audit.view">
  <div class="page-head"><div><p class="eyebrow">Oversight</p><h1>Audit log</h1><p>Every sign-in, view of personal data, and change to people, offices and reports.</p></div></div>
  <div class="toolbar" role="search">
    <label class="search"><span class="sr-only">Search the audit log</span><Icon name="search" size={16} /><input placeholder="Search action, target or email" bind:value={search} oninput={() => { clearTimeout(searchTimer); searchTimer = setTimeout(() => load(1), 300); }} /></label>
    <label><span class="sr-only">Action</span><select bind:value={action} onchange={() => load(1)}><option value="">All actions</option>{#each actions as item (item)}<option value={item}>{humanize(item)}</option>{/each}</select></label>
    <label><span class="sr-only">Target</span><select bind:value={targetType} onchange={() => load(1)}><option value="">All targets</option><option value="REPORT">Reports</option><option value="STAFF">Staff</option><option value="OFFICE">Offices</option><option value="REPORTER">Reporters</option><option value="ACCOUNT">Accounts</option></select></label>
    <label class="date"><span>From</span><input type="date" bind:value={dateFrom} onchange={() => load(1)} /></label>
    <label class="date"><span>To</span><input type="date" bind:value={dateTo} onchange={() => load(1)} /></label>
  </div>
  {#if error}<div class="error" role="alert">{error}</div>
  {:else if loading && !result.items.length}<div class="skeleton"></div>
  {:else if !result.items.length}<div class="empty">No audit entries match these filters.</div>
  {:else}
    <div class="table-wrap" aria-busy={loading}>
      <table class="data">
        <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Target</th><th>IP</th><th class="actions"><span class="sr-only">Details</span></th></tr></thead>
        <tbody>
          {#each result.items as entry (entry.id)}
            {@const t = target(entry)}
            <tr>
              <td title={localDateTime(entry.created_at)}><span class="primary">{relativeTime(entry.created_at)}</span><span class="sub">{localDateTime(entry.created_at)}</span></td>
              <td>{#if entry.actor_name || entry.actor_email}<span class="primary">{entry.actor_name ?? entry.actor_email}</span><span class="sub">{roleLabel[entry.actor_type as Role] ?? humanize(entry.actor_type)}{entry.actor_name && entry.actor_email ? ` · ${entry.actor_email}` : ''}</span>{:else}<span class="muted">{entry.actor_type === 'SYSTEM' ? 'System' : humanize(entry.actor_type)}</span>{/if}</td>
              <td><span class="pill {tone(entry.action)}">{humanize(entry.action)}</span></td>
              <td>{#if t.href}<a class="row-link" href={t.href}>{t.label}</a>{:else}{t.label}{/if}</td>
              <td class="muted mono">{entry.ip_address ?? '—'}</td>
              <td class="actions">{#if details(entry).length}<button class="button ghost small" aria-expanded={expanded === entry.id} onclick={() => expanded = expanded === entry.id ? null : entry.id}>{expanded === entry.id ? 'Hide' : 'Details'}</button>{/if}</td>
            </tr>
            {#if expanded === entry.id}
              <tr class="detail"><td colspan="6"><dl>{#each details(entry) as [key, value] (key)}<div><dt>{humanize(key)}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>{/each}</dl></td></tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>
    <Pagination page={result.page} pageSize={result.page_size} total={result.total} onchange={load} />
  {/if}
</RequirePermission>

<style>
  .date{display:flex;align-items:center;gap:.4rem;font-size:.8rem;font-weight:700;color:var(--muted)}.date input{width:auto}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.8rem}
  tr.detail td{background:var(--surface-2)}
  dl{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.5rem 1.2rem;margin:0}
  dt{font-size:.72rem;font-weight:800;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}dd{margin:.15rem 0 0;word-break:break-word}
</style>
