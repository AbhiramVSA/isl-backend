<script lang="ts">
  import type { Snippet } from 'svelte';
  import { auth } from '$lib/auth.svelte';
  import type { Permission } from '$lib/types';
  import Icon from './Icon.svelte';

  let { permission, children }: { permission: Permission; children: Snippet } = $props();
</script>

{#if auth.can(permission)}
  {@render children()}
{:else}
  <div class="denied panel">
    <Icon name="audit" size={28} />
    <h1>You don’t have access to this page</h1>
    <p>Your role ({auth.roleLabel}) doesn’t include this area. Ask a super admin or your office admin if you need it.</p>
    <a class="button secondary" href="/dashboard">Back to overview</a>
  </div>
{/if}

<style>
  .denied{max-width:520px;margin:4rem auto;text-align:center;display:grid;justify-items:center;gap:.4rem;padding:2rem}
  .denied :global(svg){color:var(--muted)}
  h1{font-size:1.3rem;margin:.4rem 0 0}p{color:var(--muted);line-height:1.5;margin:0 0 .8rem}
</style>
