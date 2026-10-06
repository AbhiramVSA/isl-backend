<script lang="ts">
  import Icon from './Icon.svelte';

  /**
   * The control bar shared by the recorded and live players: a scrubber with a
   * hover time, play/pause, ±10 s, speed, captions, landmark overlay and
   * fullscreen. Live adds the red LIVE pill that jumps back to the live edge.
   */
  let {
    playing,
    current,
    duration,
    buffered = 0,
    rate,
    live = false,
    atLiveEdge = false,
    overlay,
    captions = null,
    canDownload = false,
    onplay,
    onseek,
    onrate,
    onoverlay,
    oncaptions,
    onfullscreen,
    ongolive,
    ondownload,
    onrotate
  }: {
    playing: boolean;
    current: number;
    duration: number;
    buffered?: number;
    rate: number;
    live?: boolean;
    atLiveEdge?: boolean;
    overlay: boolean;
    captions?: boolean | null;
    canDownload?: boolean;
    onplay: () => void;
    onseek: (seconds: number) => void;
    onrate: (rate: number) => void;
    onoverlay: () => void;
    oncaptions?: () => void;
    onfullscreen: () => void;
    ongolive?: () => void;
    ondownload?: () => void;
    onrotate?: () => void;
  } = $props();

  let track = $state<HTMLDivElement | null>(null);
  let hoverX = $state<number | null>(null);
  let dragging = $state(false);
  let speedOpen = $state(false);
  const rates = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];

  const pct = (value: number) => (duration > 0 ? Math.min(100, Math.max(0, (value / duration) * 100)) : 0);
  const hoverTime = $derived(hoverX !== null && track ? (hoverX / track.clientWidth) * duration : null);

  export function format(seconds: number) {
    if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
    const s = Math.floor(seconds % 60), m = Math.floor(seconds / 60) % 60, h = Math.floor(seconds / 3600);
    return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
  }

  function timeAt(clientX: number) {
    if (!track) return 0;
    const rect = track.getBoundingClientRect();
    return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width)) * duration;
  }
  function down(event: PointerEvent) {
    dragging = true;
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    onseek(timeAt(event.clientX));
  }
  function move(event: PointerEvent) {
    if (!track) return;
    hoverX = Math.min(track.clientWidth, Math.max(0, event.clientX - track.getBoundingClientRect().left));
    if (dragging) onseek(timeAt(event.clientX));
  }
  function key(event: KeyboardEvent) {
    const step = event.shiftKey ? 10 : 5;
    if (event.key === 'ArrowLeft') onseek(Math.max(0, current - step));
    else if (event.key === 'ArrowRight') onseek(Math.min(duration, current + step));
    else if (event.key === 'Home') onseek(0);
    else if (event.key === 'End') (live && ongolive ? ongolive() : onseek(duration));
    else return;
    event.preventDefault();
  }
</script>

<div class="controls">
  <div
    class="track"
    bind:this={track}
    role="slider"
    tabindex="0"
    aria-label="Seek"
    aria-valuemin={0}
    aria-valuemax={Math.round(duration)}
    aria-valuenow={Math.round(current)}
    aria-valuetext={`${format(current)} of ${format(duration)}`}
    onpointerdown={down}
    onpointermove={move}
    onpointerup={() => (dragging = false)}
    onpointerleave={() => { if (!dragging) hoverX = null; }}
    onkeydown={key}
  >
    <div class="rail"><div class="buffered" style:width={`${pct(buffered)}%`}></div><div class="played" class:live-played={live && atLiveEdge} style:width={`${pct(current)}%`}></div></div>
    <div class="thumb" style:left={`${pct(current)}%`}></div>
    {#if hoverTime !== null}<div class="hover-time" style:left={`${hoverX}px`}>{live ? `-${format(duration - hoverTime)}` : format(hoverTime)}</div>{/if}
  </div>

  <div class="row">
    <button class="ctl" aria-label={playing ? 'Pause (k)' : 'Play (k)'} title={playing ? 'Pause (k)' : 'Play (k)'} onclick={onplay}>
      {#if playing}<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>
      {:else}<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true"><path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5z"/></svg>{/if}
    </button>
    <button class="ctl" aria-label="Back 10 seconds (j)" title="Back 10 s (j)" onclick={() => onseek(Math.max(0, current - 10))}><Icon name="refresh" size={18} /><span class="ten">10</span></button>
    <button class="ctl" aria-label="Forward 10 seconds (l)" title="Forward 10 s (l)" disabled={live && atLiveEdge} onclick={() => onseek(Math.min(duration, current + 10))}><span class="flip"><Icon name="refresh" size={18} /></span><span class="ten">10</span></button>

    {#if live}
      <button class="live-pill" class:edge={atLiveEdge} onclick={() => ongolive?.()} title={atLiveEdge ? 'You are watching live' : 'Jump to live'}>
        <span class="dot"></span>LIVE
      </button>
      {#if !atLiveEdge}<span class="time">-{format(duration - current)}</span>{/if}
    {:else}
      <span class="time">{format(current)} / {format(duration)}</span>
    {/if}

    <span class="spacer"></span>

    {#if captions !== null}
      <button class="ctl text" class:on={captions} aria-pressed={!!captions} title="Captions (c)" onclick={() => oncaptions?.()}>CC</button>
    {/if}
    <button class="ctl text" class:on={overlay} aria-pressed={overlay} title="Hand and body landmarks (o)" onclick={onoverlay}><Icon name="sign" size={17} /><span class="label">Landmarks</span></button>
    <div class="speed">
      <button class="ctl text" aria-haspopup="menu" aria-expanded={speedOpen} title="Playback speed" onclick={() => (speedOpen = !speedOpen)}>{rate === 1 ? '1×' : `${rate}×`}</button>
      {#if speedOpen}
        <div class="menu" role="menu">
          {#each rates as value (value)}<button role="menuitemradio" aria-checked={rate === value} class:on={rate === value} onclick={() => { onrate(value); speedOpen = false; }}>{value === 1 ? 'Normal' : `${value}×`}</button>{/each}
        </div>
      {/if}
    </div>
    {#if onrotate}
      <button class="ctl" aria-label="Rotate 90° (r)" title="Rotate 90° (r)" onclick={onrotate}>
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/></svg>
      </button>
    {/if}
    {#if canDownload}<button class="ctl" aria-label="Download" title="Download" onclick={() => ondownload?.()}><Icon name="download" size={18} /></button>{/if}
    <button class="ctl" aria-label="Fullscreen (f)" title="Fullscreen (f)" onclick={onfullscreen}>
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>
    </button>
  </div>
</div>

<style>
  .controls{position:absolute;left:0;right:0;bottom:0;z-index:5;padding:2.2rem .75rem .45rem;background:linear-gradient(transparent,#000000b8);color:#fff}
  .track{position:relative;height:16px;display:flex;align-items:center;cursor:pointer;touch-action:none}
  .track:focus-visible{outline:none}.track:focus-visible .rail{box-shadow:0 0 0 2px #7fd0e6}
  .rail{position:relative;width:100%;height:4px;border-radius:2px;background:#ffffff40;overflow:hidden;transition:height .1s}
  .track:hover .rail{height:6px}
  .buffered{position:absolute;inset:0 auto 0 0;background:#ffffff60}
  .played{position:absolute;inset:0 auto 0 0;background:#e5483f}
  .thumb{position:absolute;top:50%;width:13px;height:13px;margin-left:-6.5px;margin-top:-6.5px;border-radius:50%;background:#e5483f;transform:scale(0);transition:transform .1s}
  .track:hover .thumb,.track:focus-visible .thumb{transform:scale(1)}
  .hover-time{position:absolute;bottom:20px;transform:translateX(-50%);background:#000c;padding:.15rem .4rem;border-radius:4px;font-size:.75rem;font-variant-numeric:tabular-nums;pointer-events:none}
  .row{display:flex;align-items:center;gap:.15rem;margin-top:.15rem}
  .ctl{display:inline-flex;align-items:center;justify-content:center;gap:.3rem;position:relative;min-width:38px;height:38px;border:0;border-radius:8px;background:transparent;color:#fff;cursor:pointer;font-weight:800;font-size:.85rem}
  .ctl:hover{background:#ffffff1f}.ctl:disabled{opacity:.4;cursor:default}
  .ctl.text{padding:0 .55rem}.ctl.on{color:#7fd0e6}
  .ctl .ten{position:absolute;font-size:.55rem;font-weight:900;top:50%;left:50%;transform:translate(-50%,-45%)}
  .flip{display:inline-flex;transform:scaleX(-1)}
  .time{font-size:.82rem;font-variant-numeric:tabular-nums;margin-left:.4rem;opacity:.9}
  .spacer{flex:1}
  .live-pill{display:inline-flex;align-items:center;gap:.4rem;margin-left:.4rem;border:0;border-radius:6px;padding:.25rem .55rem;background:#ffffff26;color:#fff;font-weight:900;font-size:.75rem;letter-spacing:.05em;cursor:pointer}
  .live-pill .dot{width:8px;height:8px;border-radius:50%;background:#b8b8b8}
  .live-pill.edge{background:#e5483f}.live-pill.edge .dot{background:#fff;animation:blink 1.4s infinite}
  @keyframes blink{50%{opacity:.35}}
  .speed{position:relative}
  .menu{position:absolute;right:0;bottom:44px;background:#1c1c1ce8;border-radius:10px;padding:.35rem;display:grid;min-width:110px;backdrop-filter:blur(6px)}
  .menu button{border:0;background:transparent;color:#fff;text-align:left;padding:.45rem .7rem;border-radius:6px;cursor:pointer;font-weight:600}
  .menu button:hover{background:#ffffff1f}.menu button.on{color:#7fd0e6}
  @media(max-width:560px){.label{display:none}.time{font-size:.75rem}}
</style>
