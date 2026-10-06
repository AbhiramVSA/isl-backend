<script lang="ts">
  import { goto } from '$app/navigation';
  import { api, FriendlyError, loadProfile } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';
  let email = $state(''); let password = $state(''); let error = $state(''); let busy = $state(false); let reveal = $state(false);
  async function submit(event: SubmitEvent) {
    event.preventDefault(); error = ''; busy = true;
    try {
      const result = await api<{ access_token: string; refresh_token: string }>('/auth/officers/login', { method: 'POST', body: JSON.stringify({ email: email.trim(), password }) });
      auth.save(result.access_token, result.refresh_token);
      await loadProfile();
      goto('/dashboard');
    } catch (err) {
      auth.clear();
      error = err instanceof FriendlyError ? err.message : 'Unable to sign in.';
    } finally { busy = false; }
  }
</script>
<svelte:head><title>Sign in · Equal</title></svelte:head>
<div class="login-page">
  <section class="intro-side" aria-hidden="true">
    <div class="brand-row"><img src="/cid-seal.png" alt="" width="64" height="64" /><div><strong>Equal</strong><span>Andhra Pradesh Police · Crime Investigation Department</span></div></div>
    <p class="tagline">Equal Assistance and Universal Legal assistance</p>
    <h2>Every emergency, understood.</h2>
    <p>Reports signed in Indian Sign Language reach the right office with a written situation report, live location and video.</p>
    <ul><li>Live sign-language transcription</li><li>Routing to the nearest response office</li></ul>
  </section>
  <section class="login-card">
    <img class="card-seal" src="/cid-seal.png" alt="AP Police CID" width="56" height="56" />
    <p class="eyebrow">Equal responder console</p><h1>Sign in</h1>
    <p class="intro">Use the staff account your administrator created for you.</p>
    {#if error}<div class="error" role="alert">{error}</div>{/if}
    <form onsubmit={submit}>
      <label class="field">Email address<input type="email" bind:value={email} autocomplete="username" required /></label>
      <label class="field">Password
        <span class="password"><input type={reveal ? 'text' : 'password'} bind:value={password} autocomplete="current-password" required /><button type="button" class="button ghost small" onclick={() => reveal = !reveal} aria-pressed={reveal}>{reveal ? 'Hide' : 'Show'}</button></span>
      </label>
      <button class="button" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
    </form>
    <p class="help">Forgotten your password? Your office admin or a super admin can reset it.</p>
  </section>
</div>
<style>
  .login-page{min-height:100vh;display:grid;grid-template-columns:1.1fr 1fr;background:var(--bg)}
  .intro-side{background:linear-gradient(160deg,var(--navy),#0b2230);color:#fff;padding:clamp(2rem,6vw,5rem);display:flex;flex-direction:column;justify-content:center;gap:1rem}
  .brand-row{display:flex;align-items:center;gap:.9rem}.brand-row img{width:64px;height:64px;border-radius:50%;background:#fff;padding:3px}
  .brand-row div{display:grid}.brand-row strong{font-size:1.6rem;letter-spacing:-.02em}.brand-row span{color:#a9c3cd;font-size:.8rem;font-weight:600}
  .tagline{color:#7fd0e6!important;font-weight:700;margin-top:1.2rem!important}
  .card-seal{display:none;width:56px;height:56px;margin-bottom:.8rem}
  .intro-side h2{font-size:clamp(1.8rem,3.4vw,2.8rem);letter-spacing:-.03em;margin:1.2rem 0 0;max-width:15ch;line-height:1.1}
  .intro-side p{color:#bfd3db;max-width:44ch;line-height:1.6;margin:0}
  .intro-side ul{list-style:none;padding:0;margin:.8rem 0 0;display:grid;gap:.55rem;color:#d9e7ec}
  .intro-side li::before{content:'✓';display:inline-grid;place-items:center;width:20px;height:20px;border-radius:50%;background:#ffffff1f;color:#7fd0e6;margin-right:.6rem;font-size:.75rem;font-weight:900}
  .login-card{align-self:center;justify-self:center;width:min(420px,calc(100% - 2rem));padding:2rem 0}
  h1{margin:.2rem 0;font-size:2rem;letter-spacing:-.02em}.intro,.help{color:var(--muted);line-height:1.5}.error{margin:1rem 0}
  form{display:grid;gap:1rem;margin-top:1.4rem}
  .password{position:relative;display:block}.password input{padding-right:4.5rem}.password .button{position:absolute;right:.3rem;top:50%;transform:translateY(-50%)}
  form>.button{min-height:46px;margin-top:.3rem}.help{font-size:.84rem;margin:1.5rem 0 0}
  @media(max-width:860px){.login-page{grid-template-columns:1fr}.intro-side{display:none}.card-seal{display:block}}
</style>
