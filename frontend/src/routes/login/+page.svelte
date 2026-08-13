<script lang="ts">
  import { goto } from '$app/navigation';
  import { api, FriendlyError } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';
  let email = $state(''); let password = $state(''); let error = $state(''); let busy = $state(false);
  async function submit(event: SubmitEvent) {
    event.preventDefault(); error = ''; busy = true;
    try { const result = await api<{access_token:string;refresh_token:string}>('/auth/officers/login', { method:'POST', body:JSON.stringify({email,password}) }); auth.save(result.access_token,result.refresh_token); const me = await api<{name:string;offices:string[]}>('/auth/me'); auth.name = me.name; auth.office = me.offices.join(', '); localStorage.setItem('officer_name',me.name); localStorage.setItem('officer_office',auth.office); goto('/dashboard'); }
    catch (err) { error = err instanceof FriendlyError ? err.message : 'Unable to sign in.'; } finally { busy = false; }
  }
</script>
<svelte:head><title>Sign in | Sign Response</title></svelte:head>
<div class="login-page">
  <section class="login-card">
    <div class="mark">+</div><p class="eyebrow">Sign Response</p><h1>Welcome back</h1><p class="intro">Sign in to assist deaf and hard-of-hearing people and respond to reports assigned to your office.</p>
    {#if error}<div class="error" role="alert">{error}</div>{/if}
    <form onsubmit={submit}>
      <label>Email address<input type="email" bind:value={email} autocomplete="username" required /></label>
      <label>Password<input type="password" bind:value={password} autocomplete="current-password" required /></label>
      <button class="button" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
    </form>
    <p class="help">Officer access is created by an administrator. Contact your supervisor if you need help.</p>
  </section>
</div>
<style>
  .login-page{min-height:100vh;display:grid;place-items:center;padding:1rem;background:linear-gradient(135deg,#e7eff1,#f7f8f8)}.login-card{width:min(430px,100%);background:white;border:1px solid var(--line);border-radius:14px;padding:clamp(1.4rem,5vw,2.4rem);box-shadow:0 16px 45px #153b5018}.mark{display:grid;place-items:center;width:52px;height:58px;background:var(--navy);color:white;font-size:2rem;font-weight:900;clip-path:polygon(50% 0,95% 20%,87% 75%,50% 100%,13% 75%,5% 20%)}h1{margin:.3rem 0;font-size:2rem;color:#173746}.intro,.help{color:var(--muted);line-height:1.5}.error{margin:1rem 0}form{display:grid;gap:1rem;margin-top:1.4rem}label{display:grid;gap:.4rem;font-weight:700;font-size:.9rem}input{min-height:48px;border:1px solid #bac8ce;border-radius:7px;padding:.7rem;font-size:1rem}input:focus{outline:3px solid #256f8330;border-color:var(--blue)}.button{margin-top:.3rem}.help{font-size:.82rem;margin:1.5rem 0 0}
</style>
