<script lang="ts">
  import { api, errorMessage } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';
  import { toast } from '$lib/toast.svelte';
  import { categoryLabel, priorityLabel, statusLabel, type AdminReport, type OfficerLoad, type Priority, type Report, type ReportStatus } from '$lib/types';
  import Icon from './Icon.svelte';
  import Modal from './Modal.svelte';

  let { report, onchange, compact = false }: { report: Report; onchange?: (updated: AdminReport) => void; compact?: boolean } = $props();

  const closed = $derived(report.status === 'RESOLVED' || report.status === 'CANCELLED');
  const canAssign = $derived(auth.can('reports.assign') && !closed);
  const canPrioritize = $derived(auth.can('reports.prioritize'));
  const canOverride = $derived(auth.can('reports.override'));
  let busy = $state(false);

  // --- assign ---
  let assignOpen = $state(false); let candidates = $state<OfficerLoad[]>([]); let loadingCandidates = $state(false);
  let choice = $state<number | 'queue' | null>(null); let assignReason = $state('');
  async function openAssign() {
    assignOpen = true; choice = report.assigned_officer?.id ?? null; assignReason = ''; loadingCandidates = true;
    try { candidates = await api<OfficerLoad[]>(`/admin/reports/${report.public_id}/assignable`); }
    catch (e) { toast.error(errorMessage(e, 'Officers could not be loaded.')); assignOpen = false; }
    finally { loadingCandidates = false; }
  }
  async function assign() {
    if (choice === null) return;
    busy = true;
    try {
      const updated = await api<AdminReport>(`/admin/reports/${report.public_id}/assign`, { method: 'POST', body: JSON.stringify({ officer_id: choice === 'queue' ? null : choice, reason: assignReason || null }) });
      toast.success(updated.assigned_officer ? `Assigned to ${updated.assigned_officer.name}.` : 'Returned to the open queue.');
      assignOpen = false; onchange?.(updated);
    } catch (e) { toast.error(errorMessage(e, 'The report could not be assigned.')); }
    finally { busy = false; }
  }

  // --- priority ---
  let priorityOpen = $state(false); let priority = $state<Priority>('NORMAL'); let priorityReason = $state('');
  function openPriority() { priority = report.priority; priorityReason = ''; priorityOpen = true; }
  async function savePriority(event: SubmitEvent) {
    event.preventDefault(); busy = true;
    try {
      const updated = await api<AdminReport>(`/admin/reports/${report.public_id}/priority`, { method: 'PATCH', body: JSON.stringify({ priority, reason: priorityReason }) });
      toast.success(`Priority set to ${priorityLabel[updated.priority]}.`); priorityOpen = false; onchange?.(updated);
    } catch (e) { toast.error(errorMessage(e, 'The priority could not be changed.')); }
    finally { busy = false; }
  }

  // --- status override ---
  let statusOpen = $state(false); let status = $state<ReportStatus>('NEW'); let statusReason = $state('');
  const statusOptions: { value: ReportStatus; hint: string }[] = [
    { value: 'NEW', hint: 'Reopen and return to the open queue' },
    { value: 'RESPONDING', hint: 'An officer is on the way' },
    { value: 'ARRIVED', hint: 'An officer is on scene' },
    { value: 'RESOLVED', hint: 'Close as handled' },
    { value: 'CANCELLED', hint: 'Close as duplicate, test or false report' }
  ];
  function openStatus() { status = report.status === 'CANCELLED' ? 'NEW' : 'CANCELLED'; statusReason = ''; statusOpen = true; }
  async function saveStatus(event: SubmitEvent) {
    event.preventDefault(); busy = true;
    try {
      const updated = await api<AdminReport>(`/admin/reports/${report.public_id}/status`, { method: 'POST', body: JSON.stringify({ status, reason: statusReason }) });
      toast.success(`Status set to ${statusLabel[updated.status]}.`); statusOpen = false; onchange?.(updated);
    } catch (e) { toast.error(errorMessage(e, 'The status could not be changed.')); }
    finally { busy = false; }
  }
</script>

{#if canAssign || canPrioritize || canOverride}
  <div class="case-actions" class:compact>
    {#if canAssign}<button class="button {compact ? 'ghost small' : 'secondary'}" onclick={openAssign}><Icon name="assign" size={16} />{report.assigned_officer ? 'Reassign' : 'Assign'}</button>{/if}
    {#if canPrioritize}<button class="button {compact ? 'ghost small' : 'secondary'}" onclick={openPriority}><Icon name="flag" size={16} />Priority</button>{/if}
    {#if canOverride}<button class="button {compact ? 'ghost small' : 'secondary'}" onclick={openStatus}><Icon name="edit" size={16} />Status</button>{/if}
  </div>
{/if}

<Modal bind:open={assignOpen} title="Assign report" description={`${report.title || categoryLabel(report.category)} · ${report.office.name}. Only officers in this office are listed.`}>
  {#if loadingCandidates}<div class="skeleton short"></div>
  {:else}
    <div class="options" role="radiogroup" aria-label="Officer">
      {#each candidates as officer (officer.officer_id)}
        <label class="option" class:current={report.assigned_officer?.id === officer.officer_id}>
          <input type="radio" name="officer" value={officer.officer_id} bind:group={choice} />
          <span class="who"><strong>{officer.name}</strong><small>{report.assigned_officer?.id === officer.officer_id ? 'Currently assigned · ' : ''}{officer.active} active · {officer.resolved} resolved</small></span>
          <span class="load" class:busy={officer.active >= 3} title="Active reports">{officer.active}</span>
        </label>
      {:else}
        <p class="muted">No active officers belong to {report.office.name}. Add someone from Staff & roles first.</p>
      {/each}
      {#if report.assigned_officer && !['RESPONDING', 'ARRIVED'].includes(report.status)}
        <label class="option"><input type="radio" name="officer" value="queue" bind:group={choice} /><span class="who"><strong>Return to open queue</strong><small>Any officer in the office can take it</small></span></label>
      {/if}
    </div>
    <label class="field reason">Note <small>optional, recorded on the timeline</small><input bind:value={assignReason} maxlength="500" placeholder="e.g. Closest unit" /></label>
  {/if}
  {#snippet footer()}
    <button class="button secondary" onclick={() => assignOpen = false}>Cancel</button>
    <button class="button" disabled={busy || choice === null || choice === report.assigned_officer?.id} onclick={assign}>{busy ? 'Saving…' : 'Assign'}</button>
  {/snippet}
</Modal>

<Modal bind:open={priorityOpen} size="sm" title="Change priority" description="The reporter’s answers set the starting priority; change it when you know more.">
  <form id="priority-form" class="stack" onsubmit={savePriority}>
    <div class="segmented" role="radiogroup" aria-label="Priority">
      {#each ['CRITICAL', 'HIGH', 'NORMAL'] as const as value (value)}
        <label class="seg {value.toLowerCase()}" class:on={priority === value}><input type="radio" bind:group={priority} {value} />{priorityLabel[value]}</label>
      {/each}
    </div>
    <label class="field">Reason<textarea bind:value={priorityReason} required minlength="3" maxlength="500" placeholder="Why the change?"></textarea></label>
  </form>
  {#snippet footer()}
    <button class="button secondary" onclick={() => priorityOpen = false}>Cancel</button>
    <button class="button" form="priority-form" disabled={busy || priority === report.priority}>Save priority</button>
  {/snippet}
</Modal>

<Modal bind:open={statusOpen} size="sm" title="Override status" description={`Currently ${statusLabel[report.status]}. Overrides skip the normal officer workflow and are audited.`}>
  <form id="status-form" class="stack" onsubmit={saveStatus}>
    <div class="options">
      {#each statusOptions as option (option.value)}
        <label class="option" class:disabled={option.value === report.status}><input type="radio" bind:group={status} value={option.value} disabled={option.value === report.status} /><span class="who"><strong>{statusLabel[option.value]}</strong><small>{option.hint}</small></span></label>
      {/each}
    </div>
    <label class="field">Reason<textarea bind:value={statusReason} required minlength="3" maxlength="500"></textarea></label>
  </form>
  {#snippet footer()}
    <button class="button secondary" onclick={() => statusOpen = false}>Cancel</button>
    <button class={status === 'CANCELLED' ? 'button danger' : 'button'} form="status-form" disabled={busy || status === report.status}>Set {statusLabel[status]}</button>
  {/snippet}
</Modal>

<style>
  .case-actions{display:flex;gap:.4rem;flex-wrap:wrap}.case-actions.compact{gap:.1rem;justify-content:flex-end;flex-wrap:nowrap}
  .stack{display:grid;gap:1rem}
  .options{display:grid;gap:.4rem;max-height:46vh;overflow:auto}
  .option{display:flex;align-items:center;gap:.7rem;border:1px solid var(--line);border-radius:9px;padding:.65rem .75rem;cursor:pointer}
  .option:has(input:checked){border-color:var(--blue);background:var(--blue-soft)}
  .option.disabled{opacity:.5;cursor:default}
  .option input{accent-color:var(--blue);width:16px;height:16px}
  .who{display:grid;flex:1}.who small{color:var(--muted);font-size:.8rem}
  .load{display:grid;place-items:center;min-width:28px;height:28px;border-radius:50%;background:var(--green-soft);color:#176247;font-weight:800;font-size:.85rem}.load.busy{background:var(--amber-soft);color:#8a5100}
  .reason{margin-top:1rem}
  .skeleton.short{height:120px}
  .segmented{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--line-strong);border-radius:9px;overflow:hidden}
  .seg{display:flex;justify-content:center;padding:.6rem;font-weight:700;cursor:pointer;border-right:1px solid var(--line)}.seg:last-child{border-right:0}
  .seg input{position:absolute;opacity:0;pointer-events:none}
  .seg:has(input:focus-visible){box-shadow:inset var(--focus)}
  .seg.on.critical{background:var(--red);color:#fff}.seg.on.high{background:var(--amber);color:#fff}.seg.on.normal{background:var(--blue);color:#fff}
</style>
