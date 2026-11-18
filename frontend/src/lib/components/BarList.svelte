<script lang="ts">
  // Horizontal bars with the value printed beside each one; identity is the text label.
  type Item = { key: string; label: string; count: number; color?: string };
  let { items, empty = 'No data for this period.' }: { items: Item[]; empty?: string } = $props();
  const max = $derived(Math.max(1, ...items.map((item) => item.count)));
  const total = $derived(items.reduce((sum, item) => sum + item.count, 0));
</script>

{#if total === 0}
  <p class="muted">{empty}</p>
{:else}
  <ul>
    {#each items as item (item.key)}
      <li title={`${item.label}: ${item.count} (${Math.round((item.count / total) * 100)}%)`}>
        <span class="label">{item.label}</span>
        <span class="track"><span class="bar" style:width={`${(item.count / max) * 100}%`} style:background={item.color ?? '#2a78d6'}></span></span>
        <span class="value">{item.count}</span>
      </li>
    {/each}
  </ul>
{/if}

<style>
  ul{list-style:none;margin:0;padding:0;display:grid;gap:.55rem}
  li{display:grid;grid-template-columns:minmax(90px,38%) 1fr 2.5rem;align-items:center;gap:.6rem;font-size:.86rem}
  .label{color:var(--ink-2);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .track{height:12px;display:block}
  .bar{display:block;height:100%;min-width:3px;border-radius:0 4px 4px 0}
  .value{text-align:right;font-weight:750;font-variant-numeric:tabular-nums;color:var(--ink)}
</style>
