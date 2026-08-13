<script lang="ts">
  import { onMount } from 'svelte';import { api } from '$lib/api/client';import { auth } from '$lib/auth.svelte';
  let profile=$state<{name:string;email:string;role:string}|null>(null);let sharing=$state(false);let locationMessage=$state('Location sharing is off.');
  onMount(async()=>{try{profile=await api('/auth/me')}catch{}});
  function share(){if(!navigator.geolocation){locationMessage='Location sharing is not supported on this device.';return}navigator.geolocation.getCurrentPosition(()=>{sharing=true;locationMessage='Your location is available while this app is open.'},()=>locationMessage='Location permission was not granted.');}
</script>
<div class="page-head"><div><p class="eyebrow">Officer account</p><h1>Profile</h1><p>Manage this device’s response settings.</p></div></div>
<section class="panel profile"><div class="avatar">{(profile?.name??auth.name??'O').charAt(0)}</div><div><h2>{profile?.name??auth.name??'Officer'}</h2><p>{profile?.email??''}</p></div></section>
<section class="panel location"><div><h2>Share My Location</h2><p>{locationMessage}</p><small>Location is requested only when you enable it and is not continuously tracked after you leave the app.</small></div><button class="button secondary" onclick={share} disabled={sharing}>{sharing?'Sharing enabled':'Enable location'}</button></section>
<style>.profile{display:flex;align-items:center;gap:1rem;margin-bottom:1rem}.avatar{display:grid;place-items:center;width:58px;height:58px;border-radius:50%;background:var(--navy);color:white;font-size:1.5rem;font-weight:800}.profile h2,.profile p,.location h2,.location p{margin:.15rem 0}.profile p,.location p,.location small{color:var(--muted)}.location{display:flex;align-items:center;justify-content:space-between;gap:2rem}.location small{display:block;margin-top:.7rem;max-width:650px;line-height:1.5}@media(max-width:600px){.location{display:grid}.location button{width:100%}}</style>

