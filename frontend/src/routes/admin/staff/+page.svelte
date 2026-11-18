<script lang="ts">
  import { onMount } from 'svelte';
  import { page as current } from '$app/state';
  import { api, errorMessage, qs } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';
  import { toast } from '$lib/toast.svelte';
  import { permissionGroups, temporaryPassword } from '$lib/permissions';
  import { relativeTime } from '$lib/time';
  import Icon from '$lib/components/Icon.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import Pagination from '$lib/components/Pagination.svelte';
  import RequirePermission from '$lib/components/RequirePermission.svelte';
  import type { AccountStatus, AdminOffice, Page, Role, RoleInfo, Staff } from '$lib/types';

  const PAGE_SIZE = 25;
  let result = $state<Page<Staff>>({ items: [], page: 1, page_size: PAGE_SIZE, total: 0 });
  let roles = $state<RoleInfo[]>([]);
  let offices = $state<AdminOffice[]>([]);
  let loading = $state(true);
  let error = $state('');
  let search = $state(''); let roleFilter = $state<Role | ''>(''); let officeFilter = $state<number | ''>(Number(current.url.searchParams.get('office')) || ''); let statusFilter = $state<AccountStatus | ''>('');
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  const canManage = $derived(auth.can('staff.manage'));
  const grantable = $derived(roles.filter((role) => role.grantable));
  // Office admins may only place people in offices they belong to.
  const assignableOffices = $derived(
    offices.filter((office) => office.active && (auth.profile?.global_scope || auth.profile?.office_ids.includes(office.id)))
  );

  async function load(page = 1) {
    loading = true;
    try {
      result = await api<Page<Staff>>(`/admin/staff${qs({ page, page_size: PAGE_SIZE, search: search.trim(), role: roleFilter, office_id: officeFilter, status: statusFilter })}`);
      error = '';
    } catch (e) { error = errorMessage(e, 'Staff are unavailable.'); }
    finally { loading = false; }
  }
  function searchChanged() { clearTimeout(searchTimer); searchTimer = setTimeout(() => load(1), 300); }

  onMount(async () => {
    if (!auth.can('staff.view')) return;
    load();
    try { [roles, offices] = await Promise.all([api<RoleInfo[]>('/admin/roles'), api<AdminOffice[]>('/admin/offices')]); }
    catch (e) { toast.error(errorMessage(e, 'Roles could not be loaded.')); }
  });

  // --- create / edit ---------------------------------------------------------
  type Form = { name: string; email: string; phone: string; badge_number: string; rank: string; role: Role; office_ids: number[]; password: string };
  let editing = $state<Staff | null>(null);
  let formOpen = $state(false);
  let form = $state<Form>(blank());
  let formError = $state('');
  let saving = $state(false);
  const selectedRole = $derived(roles.find((role) => role.role === form.role));

  function blank(): Form {
    return { name: '', email: '', phone: '', badge_number: '', rank: '', role: 'OFFICER', office_ids: auth.profile?.global_scope ? [] : [...(auth.profile?.office_ids ?? [])].slice(0, 1), password: temporaryPassword() };
  }
  function openCreate() { editing = null; form = blank(); formError = ''; formOpen = true; }
  function openEdit(person: Staff) {
    editing = person;
    form = { name: person.name, email: person.email, phone: person.phone ?? '', badge_number: person.badge_number, rank: person.rank ?? '', role: person.role, office_ids: person.offices.map((o) => o.id), password: '' };
    formError = ''; formOpen = true;
  }
  function toggleOffice(id: number) {
    form.office_ids = form.office_ids.includes(id) ? form.office_ids.filter((item) => item !== id) : [...form.office_ids, id];
  }
  async function save(event: SubmitEvent) {
    event.preventDefault(); saving = true; formError = '';
    const body: Record<string, unknown> = { name: form.name.trim(), email: form.email.trim(), phone: form.phone.trim() || null, rank: form.rank.trim() || null,
      // Memberships outside the editor's offices are kept by the server; send only the ones shown.
      office_ids: form.office_ids.filter((id) => assignableOffices.some((office) => office.id === id)) };
    if (form.badge_number.trim()) body.badge_number = form.badge_number.trim();
    const isSelf = editing?.account_id === auth.profile?.account_id;
    if (!isSelf) body.role = form.role;
    try {
      if (editing) {
        await api<Staff>(`/admin/staff/${editing.id}`, { method: 'PATCH', body: JSON.stringify(body) });
        toast.success(`${form.name} updated.${editing.role !== form.role ? ' They will need to sign in again.' : ''}`);
      } else {
        await api<Staff>('/admin/staff', { method: 'POST', body: JSON.stringify({ ...body, password: form.password }) });
        toast.success(`${form.name} added. Share their temporary password securely.`);
      }
      formOpen = false; await load(editing ? result.page : 1);
    } catch (e) { formError = errorMessage(e, 'This person could not be saved.'); }
    finally { saving = false; }
  }

  // --- status / password -----------------------------------------------------
  let statusTarget = $state<Staff | null>(null); let statusOpen = $state(false); let statusReason = $state('');
  function askStatus(person: Staff) { statusTarget = person; statusReason = ''; statusOpen = true; }
  async function applyStatus() {
    if (!statusTarget) return;
    const next: AccountStatus = statusTarget.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE';
    saving = true;
    try {
      await api(`/admin/staff/${statusTarget.id}/status`, { method: 'POST', body: JSON.stringify({ status: next, reason: statusReason || null }) });
      toast.success(next === 'DISABLED' ? `${statusTarget.name} can no longer sign in.` : `${statusTarget.name} can sign in again.`);
      statusOpen = false; await load(result.page);
    } catch (e) { toast.error(errorMessage(e, 'The account could not be changed.')); }
    finally { saving = false; }
  }

  let resetTarget = $state<Staff | null>(null); let resetOpen = $state(false); let newPassword = $state(''); let resetDone = $state(false);
  function askReset(person: Staff) { resetTarget = person; newPassword = temporaryPassword(); resetDone = false; resetOpen = true; }
  async function applyReset() {
    if (!resetTarget) return;
    saving = true;
    try { await api(`/admin/staff/${resetTarget.id}/password`, { method: 'POST', body: JSON.stringify({ password: newPassword }) }); resetDone = true; }
    catch (e) { toast.error(errorMessage(e, 'The password could not be reset.')); }
    finally { saving = false; }
  }
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); toast.success('Copied to clipboard.'); } catch { toast.error('Copy is not available here; select the text instead.'); }
  }

  let rolesOpen = $state(false);
  function canEdit(person: Staff) {
    if (!canManage) return false;
    if (auth.profile?.global_scope) return true;
    return person.role === 'OFFICER' || person.role === 'DISPATCHER' || person.account_id === auth.profile?.account_id;
  }
</script>

<svelte:head><title>Staff & roles · Equal</title></svelte:head>
<RequirePermission permission="staff.view">
  <div class="page-head">
    <div><p class="eyebrow">Management</p><h1>Staff & roles</h1><p>{auth.profile?.global_scope ? 'Everyone with access to the responder console.' : `People in ${auth.office ?? 'your offices'}.`}</p></div>
    <div class="page-actions">
      <button class="button secondary" onclick={() => rolesOpen = true}><Icon name="audit" size={16} />Roles & permissions</button>
      {#if canManage}<button class="button" onclick={openCreate}><Icon name="plus" size={16} />Add staff</button>{/if}
    </div>
  </div>

  <div class="toolbar" role="search">
    <label class="search"><span class="sr-only">Search staff</span><Icon name="search" size={16} /><input placeholder="Search name, email or badge" bind:value={search} oninput={searchChanged} /></label>
    <label><span class="sr-only">Role</span><select bind:value={roleFilter} onchange={() => load(1)}><option value="">All roles</option>{#each roles as role (role.role)}<option value={role.role}>{role.label}</option>{/each}</select></label>
    <label><span class="sr-only">Office</span><select bind:value={officeFilter} onchange={() => load(1)}><option value="">All offices</option>{#each offices as office (office.id)}<option value={office.id}>{office.name}</option>{/each}</select></label>
    <label><span class="sr-only">Status</span><select bind:value={statusFilter} onchange={() => load(1)}><option value="">Any status</option><option value="ACTIVE">Active</option><option value="DISABLED">Disabled</option></select></label>
  </div>

  {#if error}<div class="error" role="alert">{error}</div>
  {:else if loading && !result.items.length}<div class="skeleton"></div>
  {:else if !result.items.length}<div class="empty">No staff match these filters.</div>
  {:else}
    <div class="table-wrap" aria-busy={loading}>
      <table class="data">
        <thead><tr><th>Name</th><th>Role</th><th>Offices</th><th>Status</th><th class="num">Open reports</th><th>Last sign-in</th><th class="actions"><span class="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {#each result.items as person (person.id)}
            <tr class:inactive={person.status !== 'ACTIVE'}>
              <td><span class="primary">{person.name}</span>{#if person.account_id === auth.profile?.account_id}<span class="pill plain you">You</span>{/if}<span class="sub">{person.email} · {person.badge_number}</span></td>
              <td><span class="pill role {person.role}">{person.role_label}</span></td>
              <td>{#if person.offices.length}{person.offices.map((o) => o.name).join(', ')}{:else}<span class="muted">{person.role === 'ADMIN' || person.role === 'AUDITOR' ? 'All offices' : 'None'}</span>{/if}</td>
              <td>{#if person.status === 'ACTIVE'}<span class="pill ok">Active</span>{:else}<span class="pill off">Disabled</span>{/if}</td>
              <td class="num">{person.open_reports}</td>
              <td>{person.last_login_at ? relativeTime(person.last_login_at) : 'Never'}</td>
              <td class="actions">
                {#if canEdit(person)}
                  <button class="button ghost small" onclick={() => openEdit(person)}><Icon name="edit" size={15} />Edit</button>
                  <button class="icon-button" title="Reset password" aria-label={`Reset password for ${person.name}`} onclick={() => askReset(person)}><Icon name="key" size={16} /></button>
                  {#if person.account_id !== auth.profile?.account_id}
                    <button class="icon-button" title={person.status === 'ACTIVE' ? 'Disable account' : 'Enable account'} aria-label={`${person.status === 'ACTIVE' ? 'Disable' : 'Enable'} ${person.name}`} onclick={() => askStatus(person)}><Icon name={person.status === 'ACTIVE' ? 'ban' : 'check'} size={16} /></button>
                  {/if}
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <Pagination page={result.page} pageSize={result.page_size} total={result.total} onchange={load} />
  {/if}
</RequirePermission>

<Modal bind:open={formOpen} title={editing ? `Edit ${editing.name}` : 'Add staff member'} description={editing ? 'Changing someone’s role signs them out everywhere.' : 'They sign in at this console with the email and temporary password below.'} size="lg">
  <form id="staff-form" class="form-grid" onsubmit={save}>
    {#if formError}<div class="error full" role="alert">{formError}</div>{/if}
    <label class="field">Full name<input bind:value={form.name} required minlength="2" maxlength="120" autocomplete="off" /></label>
    <label class="field">Email<input type="email" bind:value={form.email} required autocomplete="off" /></label>
    <label class="field">Phone <small>optional</small><input type="tel" bind:value={form.phone} maxlength="32" /></label>
    <label class="field">Badge number <small>{editing ? '' : 'leave blank to generate'}</small><input bind:value={form.badge_number} maxlength="64" /></label>
    <label class="field">Rank / title <small>optional</small><input bind:value={form.rank} maxlength="80" placeholder="e.g. Sub-Inspector" /></label>
    <label class="field">Role
      <select bind:value={form.role} disabled={editing?.account_id === auth.profile?.account_id}>
        {#each (editing && !grantable.some((r) => r.role === editing?.role) ? [...grantable, roles.find((r) => r.role === editing?.role)!] : grantable) as role (role.role)}<option value={role.role}>{role.label}</option>{/each}
      </select>
      {#if selectedRole}<small>{selectedRole.description}</small>{/if}
    </label>
    {#if !editing}
      <div class="field full">Temporary password
        <div class="password-row"><input class="input mono" bind:value={form.password} required minlength="10" /><button type="button" class="button secondary small" onclick={() => form.password = temporaryPassword()}><Icon name="refresh" size={15} />New</button><button type="button" class="button secondary small" onclick={() => copy(form.password)}>Copy</button></div>
        <small>Share this through a secure channel. They can change it from their profile.</small>
      </div>
    {/if}
    <fieldset class="full">
      <legend>Offices {#if selectedRole?.global_scope}<small>— this role already sees every office</small>{/if}</legend>
      {#if assignableOffices.length}
        <div class="checks">{#each assignableOffices as office (office.id)}<label class="check"><input type="checkbox" checked={form.office_ids.includes(office.id)} onchange={() => toggleOffice(office.id)} />{office.name}</label>{/each}</div>
      {:else}<p class="muted">No active offices are available to you.</p>{/if}
    </fieldset>
  </form>
  {#snippet footer()}
    <button class="button secondary" type="button" onclick={() => formOpen = false}>Cancel</button>
    <button class="button" form="staff-form" disabled={saving}>{saving ? 'Saving…' : editing ? 'Save changes' : 'Add staff member'}</button>
  {/snippet}
</Modal>

<Modal bind:open={statusOpen} size="sm" title={statusTarget?.status === 'ACTIVE' ? `Disable ${statusTarget?.name}?` : `Enable ${statusTarget?.name}?`} description={statusTarget?.status === 'ACTIVE' ? 'They are signed out immediately and cannot sign in until re-enabled. Their report history is kept.' : 'They will be able to sign in again with their existing password.'}>
  <label class="field">Reason <small>recorded in the audit log</small><textarea bind:value={statusReason} maxlength="500"></textarea></label>
  {#snippet footer()}
    <button class="button secondary" onclick={() => statusOpen = false}>Cancel</button>
    <button class={statusTarget?.status === 'ACTIVE' ? 'button danger' : 'button'} disabled={saving} onclick={applyStatus}>{statusTarget?.status === 'ACTIVE' ? 'Disable account' : 'Enable account'}</button>
  {/snippet}
</Modal>

<Modal bind:open={resetOpen} size="sm" title={`Reset password for ${resetTarget?.name ?? ''}`} description={resetDone ? 'Done. They have been signed out of other devices.' : 'Their current password stops working and other devices are signed out.'}>
  <div class="field">New temporary password
    <div class="password-row"><input class="input mono" bind:value={newPassword} readonly={resetDone} minlength="10" /><button type="button" class="button secondary small" onclick={() => copy(newPassword)}>Copy</button></div>
  </div>
  {#snippet footer()}
    {#if resetDone}<button class="button" onclick={() => resetOpen = false}>Done</button>
    {:else}<button class="button secondary" onclick={() => resetOpen = false}>Cancel</button><button class="button danger" disabled={saving || newPassword.length < 10} onclick={applyReset}>Reset password</button>{/if}
  {/snippet}
</Modal>

<Modal bind:open={rolesOpen} size="lg" title="Roles & permissions" description="What each role can do. Super admins and auditors see every office; everyone else sees only the offices they belong to.">
  <div class="matrix-wrap">
    <table class="data matrix">
      <thead><tr><th>Permission</th>{#each roles as role (role.role)}<th><span class="pill role {role.role}">{role.label}</span></th>{/each}</tr></thead>
      <tbody>
        {#each permissionGroups as group (group.label)}
          <tr class="group"><td colspan={roles.length + 1}>{group.label}</td></tr>
          {#each group.items as permission (permission.key)}
            <tr><td>{permission.label}</td>{#each roles as role (role.role)}<td class="cell">{#if role.permissions.includes(permission.key)}<Icon name="check" size={16} label="Allowed" />{:else}<span class="no" aria-label="Not allowed">—</span>{/if}</td>{/each}</tr>
          {/each}
        {/each}
      </tbody>
    </table>
  </div>
  <ul class="role-notes">{#each roles as role (role.role)}<li><strong>{role.label}.</strong> {role.description}</li>{/each}</ul>
</Modal>

<style>
  .you{margin-left:.4rem;background:var(--blue-soft);color:#195a71;font-size:.68rem;padding:.05rem .45rem}
  fieldset{border:0;padding:0;margin:0}legend{font-weight:700;font-size:.84rem;color:var(--ink-2);margin-bottom:.45rem}legend small{font-weight:500;color:var(--muted)}
  .password-row{display:flex;gap:.4rem}.password-row input{flex:1}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.02em}
  .matrix-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px}
  .matrix td.cell{text-align:center;color:var(--green)}.matrix th{text-align:center}.matrix th:first-child{text-align:left}
  .matrix .no{color:#b5c0c4}.matrix tr.group td{background:var(--surface-2);font-weight:800;font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
  .role-notes{margin:1rem 0 0;padding-left:1.1rem;display:grid;gap:.35rem;color:var(--ink-2);font-size:.88rem;line-height:1.45}
</style>
