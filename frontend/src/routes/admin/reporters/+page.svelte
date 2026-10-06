<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage, qs } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';
  import { toast } from '$lib/toast.svelte';
  import { localDate, relativeTime } from '$lib/time';
  import type { AccountStatus, Page, Reporter } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import Pagination from '$lib/components/Pagination.svelte';
  import RequirePermission from '$lib/components/RequirePermission.svelte';

  const PAGE_SIZE = 25;
  let result = $state<Page<Reporter>>({ items: [], page: 1, page_size: PAGE_SIZE, total: 0 });
  let loading = $state(true); let error = $state('');
  let search = $state(''); let status = $state<AccountStatus | ''>('');
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  async function load(page = 1) {
    loading = true;
    try { result = await api<Page<Reporter>>(`/admin/reporters${qs({ page, page_size: PAGE_SIZE, search: search.trim(), status })}`); error = ''; }
    catch (e) { error = errorMessage(e, 'Reporters are unavailable.'); }
    finally { loading = false; }
  }
  onMount(() => { if (auth.can('reporters.view')) load(); });

  let target = $state<Reporter | null>(null); let open = $state(false); let reason = $state(''); let saving = $state(false);
  async function apply() {
    if (!target) return;
    const next: AccountStatus = target.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE';
    saving = true;
    try {
      await api(`/admin/reporters/${target.id}/status`, { method: 'POST', body: JSON.stringify({ status: next, reason: reason || null }) });
      toast.success(next === 'DISABLED' ? `${target.name} is blocked from the Equal app.` : `${target.name} can use the Equal app again.`);
      open = false; await load(result.page);
    } catch (e) { toast.error(errorMessage(e, 'The reporter could not be changed.')); }
    finally { saving = false; }
  }
</script>

<svelte:head><title>Reporters · Equal</title></svelte:head>
<RequirePermission permission="reporters.view">
  <div class="page-head">
    <div><p class="eyebrow">Management</p><h1>Reporters</h1><p>People using the Equal app{auth.profile?.global_scope ? '' : ' who have reported to your offices'}.</p></div>
  </div>
  <div class="toolbar" role="search">
    <label class="search"><span class="sr-only">Search reporters</span><Icon name="search" size={16} /><input placeholder="Search name, email or phone" bind:value={search} oninput={() => { clearTimeout(searchTimer); searchTimer = setTimeout(() => load(1), 300); }} /></label>
    <label><span class="sr-only">Status</span><select bind:value={status} onchange={() => load(1)}><option value="">Any status</option><option value="ACTIVE">Active</option><option value="DISABLED">Blocked</option></select></label>
  </div>
  {#if error}<div class="error" role="alert">{error}</div>
  {:else if loading && !result.items.length}<div class="skeleton"></div>
  {:else if !result.items.length}<div class="empty">No reporters match these filters.</div>
  {:else}
    <div class="table-wrap" aria-busy={loading}>
      <table class="data">
        <thead><tr><th>Reporter</th><th>Phone</th><th class="num">Reports</th><th class="num">Open</th><th>Joined</th><th>Last active</th><th>Status</th><th class="actions"><span class="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {#each result.items as person (person.id)}
            <tr class:inactive={person.status !== 'ACTIVE'}>
              <td><span class="primary">{person.name}</span><span class="sub">{person.email}</span></td>
              <td>{person.phone ?? '—'}</td>
              <td class="num">{person.total_reports}</td>
              <td class="num">{person.open_reports}</td>
              <td>{localDate(person.created_at)}</td>
              <td>{person.last_login_at ? relativeTime(person.last_login_at) : '—'}</td>
              <td>{#if person.status === 'ACTIVE'}<span class="pill ok">Active</span>{:else}<span class="pill off">Blocked</span>{/if}</td>
              <td class="actions">{#if auth.can('reporters.manage')}<button class="button ghost small" onclick={() => { target = person; reason = ''; open = true; }}>{person.status === 'ACTIVE' ? 'Block' : 'Unblock'}</button>{/if}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <Pagination page={result.page} pageSize={result.page_size} total={result.total} onchange={load} />
  {/if}
</RequirePermission>

<Modal bind:open size="sm" title={target?.status === 'ACTIVE' ? `Block ${target?.name}?` : `Unblock ${target?.name}?`} description={target?.status === 'ACTIVE' ? 'They will be signed out of the Equal app and cannot file new reports. Use this only for abuse — a blocked person cannot reach help through the app.' : 'They will be able to sign in and file reports again.'}>
  <label class="field">Reason <small>recorded in the audit log</small><textarea bind:value={reason} maxlength="500" required></textarea></label>
  {#snippet footer()}
    <button class="button secondary" onclick={() => open = false}>Cancel</button>
    <button class={target?.status === 'ACTIVE' ? 'button danger' : 'button'} disabled={saving || (target?.status === 'ACTIVE' && reason.trim().length < 3)} onclick={apply}>{target?.status === 'ACTIVE' ? 'Block reporter' : 'Unblock'}</button>
  {/snippet}
</Modal>
