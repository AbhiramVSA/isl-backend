<script lang="ts">
  // Two-series daily trend on one shared y-axis, with a crosshair tooltip.
  type Point = { date: string; created: number; resolved: number };
  let { data }: { data: Point[] } = $props();

  const series = [
    { key: 'created', label: 'Received', color: 'var(--series-1)' },
    { key: 'resolved', label: 'Resolved', color: 'var(--series-2)' }
  ] as const;

  let width = $state(640);
  const height = 240;
  const pad = { top: 16, right: 16, bottom: 28, left: 34 };
  let hover = $state<number | null>(null);

  const max = $derived(Math.max(4, ...data.flatMap((d) => [d.created, d.resolved])));
  const niceMax = $derived(Math.ceil(max / 4) * 4);
  const ticks = $derived([0, 1, 2, 3, 4].map((i) => (niceMax / 4) * i));
  const plotW = $derived(Math.max(10, width - pad.left - pad.right));
  const plotH = height - pad.top - pad.bottom;
  const x = (i: number) => pad.left + (data.length <= 1 ? plotW / 2 : (i / (data.length - 1)) * plotW);
  const y = (v: number) => pad.top + plotH - (v / niceMax) * plotH;
  const path = (key: 'created' | 'resolved') => data.map((d, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(d[key]).toFixed(1)}`).join('');
  const labelEvery = $derived(Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(plotW / 70)))));
  const fmt = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString([], { day: 'numeric', month: 'short' });

  function move(event: PointerEvent) {
    const rect = (event.currentTarget as SVGElement).getBoundingClientRect();
    const px = event.clientX - rect.left - pad.left;
    hover = Math.min(data.length - 1, Math.max(0, Math.round((px / plotW) * (data.length - 1))));
  }
  function key(event: KeyboardEvent) {
    if (event.key === 'ArrowRight') hover = Math.min(data.length - 1, (hover ?? -1) + 1);
    else if (event.key === 'ArrowLeft') hover = Math.max(0, (hover ?? data.length) - 1);
    else return;
    event.preventDefault();
  }
</script>

<div class="viz-root">
  <div class="legend" aria-hidden="true">{#each series as s (s.key)}<span><i style:background={s.color}></i>{s.label}</span>{/each}</div>
  <div class="chart" bind:clientWidth={width}>
    <!-- Focusable so keyboard users can step through days; the table view is the full alternative. -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
    <svg {width} {height} role="img" aria-label="Reports received and resolved per day. Use the arrow keys to read each day." tabindex="0" onpointermove={move} onpointerleave={() => hover = null} onkeydown={key} onblur={() => hover = null}>
      {#each ticks as tick (tick)}
        <line class="grid" x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} />
        <text class="axis" x={pad.left - 8} y={y(tick)} dy="0.32em" text-anchor="end">{tick}</text>
      {/each}
      {#each data as d, i (d.date)}{#if i % labelEvery === 0}<text class="axis" x={x(i)} y={height - 8} text-anchor="middle">{fmt(d.date)}</text>{/if}{/each}
      {#if hover !== null}<line class="crosshair" x1={x(hover)} x2={x(hover)} y1={pad.top} y2={pad.top + plotH} />{/if}
      {#each series as s (s.key)}
        <path d={path(s.key)} fill="none" stroke={s.color} stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
        {#if hover !== null}<circle cx={x(hover)} cy={y(data[hover][s.key])} r="4.5" fill={s.color} stroke="var(--surface)" stroke-width="2" />{/if}
      {/each}
    </svg>
    {#if hover !== null}
      {@const d = data[hover]}
      <div class="tooltip" style:left={`${Math.min(Math.max(x(hover), 90), width - 90)}px`} role="status">
        <strong>{new Date(`${d.date}T00:00:00`).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })}</strong>
        {#each series as s (s.key)}<span><i style:background={s.color}></i>{s.label}<b>{d[s.key]}</b></span>{/each}
      </div>
    {/if}
  </div>
</div>

<style>
  .viz-root{--series-1:#2a78d6;--series-2:#eb6834;--grid:#e7ecee;--axis:#6b7a80}
  .legend{display:flex;gap:1rem;font-size:.8rem;font-weight:650;color:var(--ink-2);margin-bottom:.4rem}
  .legend span,.tooltip span{display:flex;align-items:center;gap:.4rem}
  i{display:inline-block;width:10px;height:10px;border-radius:3px}
  .chart{position:relative}
  svg{display:block;overflow:visible;touch-action:pan-y}
  svg:focus-visible{outline:none;box-shadow:var(--focus);border-radius:6px}
  .grid{stroke:var(--grid);stroke-width:1}
  .axis{fill:var(--axis);font-size:11px;font-variant-numeric:tabular-nums}
  .crosshair{stroke:#9aa8ae;stroke-width:1;stroke-dasharray:3 3}
  .tooltip{position:absolute;top:0;transform:translateX(-50%);background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow-lg);border-radius:8px;padding:.5rem .65rem;display:grid;gap:.25rem;font-size:.8rem;pointer-events:none;min-width:150px}
  .tooltip b{margin-left:auto;padding-left:1rem;font-variant-numeric:tabular-nums}
</style>
