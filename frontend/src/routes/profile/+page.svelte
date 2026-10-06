<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage, loadProfile } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';
  import { signOut } from '$lib/session';
  import { toast } from '$lib/toast.svelte';
  import { permissionGroups } from '$lib/permissions';
  import Icon from '$lib/components/Icon.svelte';

  let sharing = $state(false); let locationMessage = $state('Location sharing is off.');
  onMount(() => { loadProfile().catch(() => {}); });
  function share() {
    if (!navigator.geolocation) { locationMessage = 'Location sharing is not supported on this device.'; return; }
    navigator.geolocation.getCurrentPosition(() => { sharing = true; locationMessage = 'Your location is available while this app is open.'; }, () => locationMessage = 'Location permission was not granted.');
  }

  let current = $state(''); let next = $state(''); let confirm = $state(''); let saving = $state(false); let formError = $state('');
  const mismatch = $derived(confirm.length > 0 && confirm !== next);
  async function changePassword(event: SubmitEvent) {
    event.preventDefault(); formError = '';
    if (next !== confirm) { formError = 'The new passwords do not match.'; return; }
    saving = true;
    try {
      await api('/auth/password', { method: 'POST', body: JSON.stringify({ current_password: current, new_password: next }) });
      current = next = confirm = '';
      toast.success('Password changed. Other devices have been signed out.');
    } catch (e) { formError = errorMessage(e, 'Your password could not be changed.'); }
    finally { saving = false; }
  }
  const allowed = $derived(permissionGroups.map((group) => ({ ...group, items: group.items.filter((item) => auth.can(item.key)) })).filter((group) => group.items.length));
</script>

<svelte:head><title>Profile · Equal</title></svelte:head>
<div class="page-head"><div><p class="eyebrow">Your account</p><h1>Profile</h1><p>Your role, offices and sign-in settings.</p></div></div>

<div class="layout">
  <div class="col">
    <section class="panel identity">
      <div class="avatar">{(auth.name ?? 'E').charAt(0)}</div>
      <div><h2>{auth.name ?? 'Signed in'}</h2><p>{auth.profile?.email ?? ''}</p><span class="pill role {auth.profile?.role ?? 'OFFICER'}">{auth.roleLabel}</span></div>
    </section>
    <section class="panel">
      <h2>Offices</h2>
      {#if auth.profile?.global_scope}<p class="muted">Your role covers every office.</p>{/if}
      {#if auth.profile?.offices.length}<ul class="offices">{#each auth.profile.offices as office (office)}<li><Icon name="office" size={16} />{office}</li>{/each}</ul>
      {:else if !auth.profile?.global_scope}<p class="muted">You are not assigned to an office yet. Ask your office admin to add you.</p>{/if}
    </section>
    <section class="panel">
      <h2>What you can do</h2>
      {#each allowed as group (group.label)}<h3>{group.label}</h3><ul class="perms">{#each group.items as item (item.key)}<li><Icon name="check" size={15} />{item.label}</li>{/each}</ul>{/each}
    </section>
  </div>
  <div class="col">
    <section class="panel">
      <h2>Change password</h2>
      <form class="stack" onsubmit={changePassword}>
        {#if formError}<div class="error" role="alert">{formError}</div>{/if}
        <label class="field">Current password<input type="password" bind:value={current} autocomplete="current-password" required /></label>
        <label class="field">New password <small>at least 10 characters</small><input type="password" bind:value={next} autocomplete="new-password" minlength="10" required /></label>
        <label class="field">Confirm new password<input type="password" bind:value={confirm} autocomplete="new-password" required aria-invalid={mismatch} />{#if mismatch}<small class="bad">Doesn’t match yet.</small>{/if}</label>
        <button class="button" disabled={saving || mismatch || next.length < 10}>{saving ? 'Saving…' : 'Change password'}</button>
      </form>
    </section>
    <section class="panel">
      <h2>Share my location</h2>
      <p class="muted">{locationMessage}</p>
      <p class="small">Location is requested only when you enable it and is not tracked after you leave the app.</p>
      <button class="button secondary" onclick={share} disabled={sharing}>{sharing ? 'Sharing enabled' : 'Enable location'}</button>
    </section>
    <button class="button secondary signout" onclick={signOut}><Icon name="logout" size={16} />Sign out of this device</button>
  </div>
</div>

<style>
  .layout{display:grid;grid-template-columns:1fr 1fr;gap:1rem;align-items:start}.col{display:grid;gap:1rem}
  .panel h2{font-size:1.05rem;margin:0 0 .8rem}
  .identity{display:flex;align-items:center;gap:1rem}.identity h2{margin:0}.identity p{margin:.15rem 0 .45rem;color:var(--muted)}
  .avatar{display:grid;place-items:center;width:60px;height:60px;border-radius:50%;background:var(--navy);color:#fff;font-size:1.5rem;font-weight:800;flex:0 0 auto}
  ul{list-style:none;padding:0;margin:0;display:grid;gap:.4rem}
  li{display:flex;align-items:center;gap:.5rem}.perms li :global(svg){color:var(--green)}
  h3{font-size:.72rem;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin:1rem 0 .4rem}h3:first-of-type{margin-top:0}
  .stack{display:grid;gap:.9rem}.bad{color:var(--red)}
  .small{font-size:.82rem;color:var(--muted);line-height:1.5}
  .signout{display:none}
  @media(max-width:900px){.layout{grid-template-columns:1fr}.signout{display:inline-flex}}
</style>
