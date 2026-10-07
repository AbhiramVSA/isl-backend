<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';
  import { toast } from '$lib/toast.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import RequirePermission from '$lib/components/RequirePermission.svelte';
  import type { AdminOffice } from '$lib/types';

  let offices = $state<AdminOffice[]>([]);
  let loading = $state(true);
  let error = $state('');
  let search = $state('');
  let showInactive = $state(true);
  const visible = $derived(
    offices.filter((office) => (showInactive || office.active) && `${office.name} ${office.address}`.toLowerCase().includes(search.trim().toLowerCase()))
  );
  const canCreate = $derived(auth.can('offices.manage'));
  const canEdit = (office: AdminOffice) => auth.can('offices.edit') && (auth.profile?.global_scope || auth.profile?.office_ids.includes(office.id));

  async function load() {
    loading = true;
    try { offices = await api<AdminOffice[]>('/admin/offices'); error = ''; }
    catch (e) { error = errorMessage(e, 'Offices are unavailable.'); }
    finally { loading = false; }
  }
  onMount(() => { if (auth.can('offices.view')) load(); });

  type Form = { name: string; address: string; latitude: number | null; longitude: number | null; service_radius: number };
  let formOpen = $state(false); let editing = $state<AdminOffice | null>(null); let saving = $state(false); let formError = $state(''); let locating = $state(false);
  let form = $state<Form>({ name: '', address: '', latitude: null, longitude: null, service_radius: 10 });
  const mapLink = $derived(form.latitude !== null && form.longitude !== null ? `https://www.openstreetmap.org/?mlat=${form.latitude}&mlon=${form.longitude}#map=14/${form.latitude}/${form.longitude}` : '');

  function openCreate() { editing = null; form = { name: '', address: '', latitude: null, longitude: null, service_radius: 10 }; formError = ''; formOpen = true; }
  function openEdit(office: AdminOffice) { editing = office; form = { name: office.name, address: office.address, latitude: office.latitude, longitude: office.longitude, service_radius: office.service_radius }; formError = ''; formOpen = true; }
  function useMyLocation() {
    if (!navigator.geolocation) { toast.error('Location is not available on this device.'); return; }
    locating = true;
    navigator.geolocation.getCurrentPosition(
      (position) => { form.latitude = +position.coords.latitude.toFixed(6); form.longitude = +position.coords.longitude.toFixed(6); locating = false; },
      () => { toast.error('Location permission was not granted.'); locating = false; },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  }
  async function save(event: SubmitEvent) {
    event.preventDefault(); saving = true; formError = '';
    try {
      if (editing) {
        await api(`/admin/offices/${editing.id}`, { method: 'PATCH', body: JSON.stringify(form) });
        toast.success(`${form.name} updated.`);
      } else {
        await api('/admin/offices', { method: 'POST', body: JSON.stringify(form) });
        toast.success(`${form.name} created. New reports nearby will be routed to it.`);
      }
      formOpen = false; await load();
    } catch (e) { formError = errorMessage(e, 'The office could not be saved.'); }
    finally { saving = false; }
  }

  let toggleTarget = $state<AdminOffice | null>(null); let toggleOpen = $state(false);
  async function applyToggle() {
    if (!toggleTarget) return;
    saving = true;
    try {
      await api(`/admin/offices/${toggleTarget.id}`, { method: 'PATCH', body: JSON.stringify({ active: !toggleTarget.active }) });
      toast.success(toggleTarget.active ? `${toggleTarget.name} deactivated.` : `${toggleTarget.name} is active again.`);
      toggleOpen = false; await load();
    } catch (e) { toast.error(errorMessage(e, 'The office could not be changed.')); }
    finally { saving = false; }
  }
</script>

<svelte:head><title>Offices · Equal</title></svelte:head>
<RequirePermission permission="offices.view">
  <div class="page-head">
    <div><p class="eyebrow">Management</p><h1>Offices</h1><p>Response offices and the area each one covers. Reports are routed to the nearest active office.</p></div>
    {#if canCreate}<div class="page-actions"><button class="button" onclick={openCreate}><Icon name="plus" size={16} />Add office</button></div>{/if}
  </div>
  <div class="toolbar">
    <label class="search"><span class="sr-only">Search offices</span><Icon name="search" size={16} /><input placeholder="Search by name or address" bind:value={search} /></label>
    <label class="check inline"><input type="checkbox" bind:checked={showInactive} />Show inactive</label>
  </div>
  {#if error}<div class="error" role="alert">{error}</div>
  {:else if loading}<div class="grid"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>
  {:else if !visible.length}<div class="empty">{offices.length ? 'No offices match your search.' : 'No offices yet.'}</div>
  {:else}
    <div class="grid">
      {#each visible as office (office.id)}
        <article class="panel office" class:inactive={!office.active}>
          <header>
            <div><h2>{office.name}</h2><p>{office.address}</p></div>
            {#if office.active}<span class="pill ok">Active</span>{:else}<span class="pill off">Inactive</span>{/if}
          </header>
          <dl>
            <div><dt>Staff</dt><dd>{office.staff_count}</dd></div>
            <div><dt>Open reports</dt><dd class:hot={office.open_reports > 0}>{office.open_reports}</dd></div>
            <div><dt>All-time</dt><dd>{office.total_reports}</dd></div>
            <div><dt>Coverage</dt><dd>{office.service_radius} km</dd></div>
          </dl>
          <footer>
            <a class="button ghost small" href={`/admin/staff?office=${office.id}`}><Icon name="staff" size={15} />Staff</a>
            <a class="button ghost small" href={`https://www.openstreetmap.org/?mlat=${office.latitude}&mlon=${office.longitude}#map=14/${office.latitude}/${office.longitude}`} target="_blank" rel="noreferrer"><Icon name="map" size={15} />Map</a>
            <span class="spacer"></span>
            {#if canEdit(office)}<button class="button secondary small" onclick={() => openEdit(office)}><Icon name="edit" size={15} />Edit</button>{/if}
            {#if canCreate}<button class="button ghost small" onclick={() => { toggleTarget = office; toggleOpen = true; }}>{office.active ? 'Deactivate' : 'Activate'}</button>{/if}
          </footer>
        </article>
      {/each}
    </div>
  {/if}
</RequirePermission>

<Modal bind:open={formOpen} title={editing ? `Edit ${editing.name}` : 'Add office'} description="The location and coverage radius decide which reports this office receives.">
  <form id="office-form" class="form-grid" onsubmit={save}>
    {#if formError}<div class="error full" role="alert">{formError}</div>{/if}
    <label class="field full">Office name<input bind:value={form.name} required minlength="2" maxlength="160" placeholder="e.g. Governorpet Police Station" /></label>
    <label class="field full">Address<input bind:value={form.address} required minlength="2" maxlength="500" /></label>
    <label class="field">Latitude<input type="number" step="any" min="-90" max="90" bind:value={form.latitude} required /></label>
    <label class="field">Longitude<input type="number" step="any" min="-180" max="180" bind:value={form.longitude} required /></label>
    <div class="full loc-row">
      <button type="button" class="button secondary small" onclick={useMyLocation} disabled={locating}><Icon name="map" size={15} />{locating ? 'Locating…' : 'Use my current location'}</button>
      {#if mapLink}<a href={mapLink} target="_blank" rel="noreferrer">Check on the map ↗</a>{/if}
    </div>
    <label class="field full">Coverage radius <small>{form.service_radius} km — reports within this distance are routed here first</small><input type="range" min="1" max="100" step="1" bind:value={form.service_radius} /></label>
  </form>
  {#snippet footer()}
    <button class="button secondary" type="button" onclick={() => formOpen = false}>Cancel</button>
    <button class="button" form="office-form" disabled={saving}>{saving ? 'Saving…' : editing ? 'Save changes' : 'Create office'}</button>
  {/snippet}
</Modal>

<Modal bind:open={toggleOpen} size="sm" title={toggleTarget?.active ? `Deactivate ${toggleTarget?.name}?` : `Activate ${toggleTarget?.name}?`} description={toggleTarget?.active ? 'New reports will no longer be routed here. Existing reports and staff stay as they are.' : 'New reports nearby will be routed here again.'}>
  {#if toggleTarget?.active && toggleTarget.open_reports}<p class="warn"><Icon name="alert" size={16} />{toggleTarget.open_reports} open report{toggleTarget.open_reports === 1 ? '' : 's'} still belong to this office.</p>{/if}
  {#snippet footer()}
    <button class="button secondary" onclick={() => toggleOpen = false}>Cancel</button>
    <button class={toggleTarget?.active ? 'button danger' : 'button'} disabled={saving} onclick={applyToggle}>{toggleTarget?.active ? 'Deactivate' : 'Activate'}</button>
  {/snippet}
</Modal>

<style>
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:1rem}
  .office{display:grid;gap:.9rem;align-content:start}.office.inactive{opacity:.72}
  .office header{display:flex;justify-content:space-between;gap:.8rem;align-items:flex-start}
  .office h2{margin:0;font-size:1.05rem}.office header p{margin:.25rem 0 0;color:var(--muted);font-size:.86rem}
  dl{display:grid;grid-template-columns:repeat(4,1fr);gap:.4rem;margin:0}
  dl div{background:var(--surface-2);border:1px solid var(--line);border-radius:8px;padding:.5rem .6rem}
  dt{font-size:.7rem;color:var(--muted);font-weight:700}dd{margin:.1rem 0 0;font-weight:800;font-size:1.1rem;font-variant-numeric:tabular-nums}dd.hot{color:var(--red)}
  footer{display:flex;gap:.3rem;align-items:center;flex-wrap:wrap;border-top:1px solid var(--line);padding-top:.7rem}.spacer{flex:1}
  .check.inline{border:0;padding:.3rem .5rem}
  .loc-row{display:flex;gap:1rem;align-items:center;flex-wrap:wrap}.loc-row a{font-size:.88rem;font-weight:600;color:var(--blue)}
  input[type=range]{min-height:auto;padding:0;border:0;accent-color:var(--blue)}
  .warn{display:flex;gap:.5rem;align-items:center;background:var(--amber-soft);color:#8a5100;border-radius:8px;padding:.7rem;margin:0;font-weight:600}
  @media(max-width:420px){dl{grid-template-columns:1fr 1fr}}
</style>
