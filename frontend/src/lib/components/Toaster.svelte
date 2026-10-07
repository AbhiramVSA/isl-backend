<script lang="ts">
  import { toast } from '$lib/toast.svelte';
  import Icon from './Icon.svelte';
</script>

<div class="toaster" aria-live="polite">
  {#each toast.items as item (item.id)}
    <div class="toast {item.kind}" role={item.kind === 'error' ? 'alert' : 'status'}>
      <Icon name={item.kind === 'success' ? 'check' : item.kind === 'error' ? 'alert' : 'info'} />
      <span>{item.message}</span>
      <button class="icon-button" aria-label="Dismiss" onclick={() => toast.dismiss(item.id)}><Icon name="close" size={16} /></button>
    </div>
  {/each}
</div>

<style>
  .toaster{position:fixed;z-index:2000;right:1rem;bottom:1rem;display:grid;gap:.5rem;width:min(380px,calc(100vw - 2rem))}
  .toast{display:flex;align-items:flex-start;gap:.6rem;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:10px;padding:.75rem .75rem .75rem .9rem;box-shadow:var(--shadow-lg);font-weight:600;font-size:.9rem;animation:rise .18s ease-out}
  .toast span{flex:1;line-height:1.4}
  .toast.success{border-left-color:var(--green)}.toast.success>:global(svg){color:var(--green)}
  .toast.error{border-left-color:var(--red)}.toast.error>:global(svg){color:var(--red)}
  .toast.info>:global(svg){color:var(--blue)}
  @keyframes rise{from{transform:translateY(8px);opacity:0}}
  @media(max-width:760px){.toaster{bottom:5rem;right:.75rem}}
</style>
