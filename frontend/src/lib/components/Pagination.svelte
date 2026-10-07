<script lang="ts">
  let { page, pageSize, total, onchange }: { page: number; pageSize: number; total: number; onchange: (page: number) => void } = $props();
  const pages = $derived(Math.max(1, Math.ceil(total / pageSize)));
  const first = $derived(total ? (page - 1) * pageSize + 1 : 0);
  const last = $derived(Math.min(page * pageSize, total));
</script>

{#if total > 0}
  <nav class="pagination" aria-label="Pagination">
    <span>{first}–{last} of {total}</span>
    <div>
      <button class="button secondary small" disabled={page <= 1} onclick={() => onchange(page - 1)}>Previous</button>
      <span class="page">Page {page} of {pages}</span>
      <button class="button secondary small" disabled={page >= pages} onclick={() => onchange(page + 1)}>Next</button>
    </div>
  </nav>
{/if}

<style>
  .pagination{display:flex;justify-content:space-between;align-items:center;gap:1rem;padding:.8rem 0;color:var(--muted);font-size:.85rem}
  .pagination div{display:flex;align-items:center;gap:.6rem}
  @media(max-width:560px){.pagination{flex-direction:column}.page{display:none}}
</style>
