<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';

  let {
    open = $bindable(false),
    title,
    description,
    size = 'md',
    children,
    footer,
    onclose
  }: {
    open?: boolean;
    title: string;
    description?: string;
    size?: 'sm' | 'md' | 'lg';
    children: Snippet;
    footer?: Snippet;
    onclose?: () => void;
  } = $props();

  let dialog = $state<HTMLDialogElement | null>(null);

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  });

  function close() { open = false; onclose?.(); }
</script>

<!-- Native <dialog>: focus trapping, Escape and inert background for free. -->
<dialog bind:this={dialog} class={size} aria-labelledby="modal-title" onclose={() => { if (open) close(); }} onclick={(event) => { if (event.target === dialog) close(); }}>
  {#if open}
    <div class="sheet">
      <header>
        <div><h2 id="modal-title">{title}</h2>{#if description}<p>{description}</p>{/if}</div>
        <button class="icon-button" type="button" aria-label="Close" onclick={close}><Icon name="close" /></button>
      </header>
      <div class="body">{@render children()}</div>
      {#if footer}<footer>{@render footer()}</footer>{/if}
    </div>
  {/if}
</dialog>

<style>
  dialog{text-align:left;white-space:normal;font-weight:normal;border:0;padding:0;border-radius:14px;background:var(--surface);color:var(--ink);box-shadow:var(--shadow-lg);width:min(560px,calc(100vw - 2rem));max-height:calc(100dvh - 2rem)}
  dialog.sm{width:min(420px,calc(100vw - 2rem))}dialog.lg{width:min(820px,calc(100vw - 2rem))}
  dialog::backdrop{background:#0b1d2766;backdrop-filter:blur(2px)}
  dialog[open]{animation:pop .16s ease-out}
  .sheet{display:flex;flex-direction:column;max-height:calc(100dvh - 2rem)}
  header{display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;padding:1.15rem 1.25rem .9rem;border-bottom:1px solid var(--line)}
  h2{margin:0;font-size:1.15rem}header p{margin:.3rem 0 0;color:var(--muted);font-size:.88rem;line-height:1.45}
  .body{padding:1.15rem 1.25rem;overflow:auto}
  footer{display:flex;justify-content:flex-end;gap:.6rem;flex-wrap:wrap;padding:.9rem 1.25rem;border-top:1px solid var(--line);background:var(--surface-2);border-radius:0 0 14px 14px}
  @keyframes pop{from{transform:translateY(6px) scale(.98);opacity:0}}
  @media(max-width:600px){dialog,dialog.sm,dialog.lg{width:100vw;max-width:100vw;margin:auto 0 0;border-radius:14px 14px 0 0}footer :global(.button){flex:1}}
</style>
