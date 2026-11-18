<script lang="ts">
  import { onDestroy, onMount, untrack } from 'svelte';
  import { api, base } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';
  import HolisticOverlay from './HolisticOverlay.svelte';
  import PlayerControls from './PlayerControls.svelte';
  import type { MotionEvent, MotionSample } from '$lib/motion';

  /**
   * Watch a caller signing in the Equal app, live, with DVR rewind.
   *
   * Frames arrive over /ws/live/<id> and are cached here; anything older than
   * the moment this page opened is fetched from the server in short segments
   * as the playhead reaches it. Pausing or seeking back leaves the live edge;
   * the LIVE pill (or End) jumps back to it.
   */
  let {
    streamId,
    onstate,
    ontime,
    onmotion,
    onmotionevent
  }: {
    streamId: string;
    onstate?: (state: { live: boolean; caption: string; transcript: string; discarded: boolean }) => void;
    /** Playhead in ms on the stream timeline (live edge or rewound), for the motion view. */
    ontime?: (ms: number, durationMs: number) => void;
    onmotion?: (samples: MotionSample[]) => void;
    onmotionevent?: (event: MotionEvent) => void;
  } = $props();

  /** Jump to a moment (ms); used by the motion timeline. */
  export function seekTo(ms: number) { seek(ms / 1000); }

  type Segment = { duration_ms: number; live: boolean; frames: { t_ms: number; jpeg: string }[] };

  let shell = $state<HTMLDivElement | null>(null);
  let canvas = $state<HTMLCanvasElement | null>(null);
  let frameCount = $state(0);
  let connected = $state(false);
  let live = $state(true);
  let discarded = $state(false);
  let mode = $state<'live' | 'dvr'>('live');
  let playing = $state(true);
  let edgeMs = $state(0);
  let playheadMs = $state(0);
  let rate = $state(1);
  let overlay = $state(false);
  let captionsOn = $state(true);
  let caption = $state('');
  let transcript = $state('');
  let aspect = $state(3 / 4);
  // Phone frames can arrive sideways; rotating here (not with CSS) also hands the
  // landmark model an upright picture, which it reads far better.
  let rotation = $state(0);
  let waiting = $state(true);
  let error = $state('');

  // Frame cache, kept sorted by time, plus which time ranges are complete.
  const times: number[] = [];
  const jpegs: string[] = [];
  let loaded: [number, number][] = [];
  let pending = false;
  let lastDrawn = -1;
  const captionTimeline: { t: number; text: string }[] = [];

  let socket: WebSocket | null = null;
  let raf = 0;
  let lastTick = 0;
  let closed = false;
  let retry = 1000;
  const image = new Image();

  const atEdge = $derived(mode === 'live');
  const currentMs = $derived(mode === 'live' ? edgeMs : playheadMs);

  function insert(t: number, jpeg: string) {
    let lo = 0, hi = times.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (times[mid] < t) lo = mid + 1; else hi = mid; }
    if (times[lo] === t) return;
    times.splice(lo, 0, t); jpegs.splice(lo, 0, jpeg);
  }
  function indexAt(t: number) {
    let lo = 0, hi = times.length - 1, found = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (times[mid] <= t) { found = mid; lo = mid + 1; } else hi = mid - 1; }
    return found;
  }
  function covered(t: number) { return loaded.some(([a, b]) => t >= a && t <= b); }
  function addRange(a: number, b: number) {
    loaded.push([a, b]);
    loaded.sort((x, y) => x[0] - y[0]);
    const merged: [number, number][] = [];
    for (const range of loaded) {
      const last = merged[merged.length - 1];
      if (last && range[0] <= last[1] + 50) last[1] = Math.max(last[1], range[1]); else merged.push([...range]);
    }
    loaded = merged;
  }

  function draw(index: number) {
    if (index < 0 || index === lastDrawn || !canvas) return;
    lastDrawn = index;
    const jpeg = jpegs[index];
    image.onload = () => {
      if (!canvas) return;
      const sideways = rotation % 180 !== 0;
      const width = sideways ? image.naturalHeight : image.naturalWidth;
      const height = sideways ? image.naturalWidth : image.naturalHeight;
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width; canvas.height = height;
        aspect = width / height;
      }
      const context = canvas.getContext('2d');
      if (!context) return;
      context.save();
      context.translate(width / 2, height / 2);
      context.rotate((rotation * Math.PI) / 180);
      context.drawImage(image, -image.naturalWidth / 2, -image.naturalHeight / 2);
      context.restore();
      frameCount++;
      waiting = false;
    };
    image.src = `data:image/jpeg;base64,${jpeg}`;
  }

  async function fetchSegment(start: number) {
    if (pending) return;
    pending = true;
    try {
      const from = Math.max(0, start - 200);
      const segment = await api<Segment>(`/officer/live/${streamId}/segment?start_ms=${from}&duration_ms=5000`);
      for (const frame of segment.frames) insert(frame.t_ms, frame.jpeg);
      const end = segment.frames.length ? Math.max(from + 5000, segment.frames[segment.frames.length - 1].t_ms) : from + 5000;
      addRange(from, Math.min(end, segment.duration_ms));
      edgeMs = Math.max(edgeMs, segment.duration_ms);
      if (!segment.live) live = false;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Part of this recording could not be loaded.';
    } finally { pending = false; }
  }

  function tick(now: number) {
    const dt = lastTick ? now - lastTick : 0;
    lastTick = now;
    if (mode === 'dvr') {
      if (playing) {
        playheadMs += dt * rate;
        if (live && playheadMs >= edgeMs - 250) { goLive(); }
        else if (!live && playheadMs >= edgeMs) { playheadMs = edgeMs; playing = false; }
      }
      if (!covered(playheadMs)) fetchSegment(playheadMs);
      else if (playing && !covered(playheadMs + 2500) && playheadMs + 2500 < edgeMs) fetchSegment(playheadMs + 2500);
      draw(indexAt(playheadMs));
    }
    raf = requestAnimationFrame(tick);
  }

  function captionAt(t: number) {
    let text = '';
    for (const entry of captionTimeline) { if (entry.t <= t) text = entry.text; else break; }
    return text;
  }
  const shownCaption = $derived(mode === 'live' ? caption : captionAt(playheadMs) || '');

  function connect() {
    if (closed) return;
    const url = new URL(base.replace(/^http/, 'ws') + `/ws/live/${streamId}`);
    url.searchParams.set('access_token', auth.accessToken ?? '');
    const ws = new WebSocket(url);
    socket = ws;
    ws.onopen = () => { connected = true; retry = 1000; error = ''; };
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'meta') {
        live = msg.live; caption = msg.caption ?? ''; transcript = msg.transcript ?? '';
        edgeMs = Math.max(edgeMs, msg.duration_ms ?? 0);
        if (!live && mode === 'live') { mode = 'dvr'; playheadMs = 0; playing = false; }
      } else if (msg.type === 'frame') {
        insert(msg.t_ms, msg.jpeg);
        // Everything from the first frame we saw onward arrives here, so it counts as loaded.
        if (!loaded.length || !covered(msg.t_ms)) addRange(msg.t_ms, msg.t_ms);
        else loaded = loaded.map(([a, b]) => (msg.t_ms >= a && msg.t_ms <= b + 2000 ? [a, Math.max(b, msg.t_ms)] : [a, b]) as [number, number]);
        edgeMs = Math.max(edgeMs, msg.t_ms);
        if (mode === 'live') draw(times.length - 1);
      } else if (msg.type === 'caption') {
        caption = msg.caption ?? ''; transcript = msg.transcript ?? '';
        if (caption) captionTimeline.push({ t: msg.t_ms, text: caption });
      } else if (msg.type === 'ended') {
        live = false;
        edgeMs = Math.max(edgeMs, msg.duration_ms ?? edgeMs);
        if (mode === 'live') { mode = 'dvr'; playheadMs = edgeMs; playing = false; }
      } else if (msg.type === 'motion') {
        onmotion?.(msg.samples);
      } else if (msg.type === 'motion.event') {
        onmotionevent?.(msg as MotionEvent);
      } else if (msg.type === 'discarded') {
        discarded = true; live = false; playing = false;
      }
      onstate?.({ live, caption, transcript, discarded });
    };
    ws.onclose = (event) => {
      connected = false; socket = null;
      if (closed || discarded) return;
      if (event.code === 4404) { error = 'This stream is no longer available.'; return; }
      if (event.code === 4410) { discarded = true; return; }
      if (event.code === 4401) { error = 'Your session has expired. Sign in again to watch.'; return; }
      setTimeout(connect, retry); retry = Math.min(retry * 2, 15000);
    };
  }

  function rotate() {
    rotation = (rotation + 90) % 360;
    const index = lastDrawn;
    lastDrawn = -1;
    draw(index >= 0 ? index : times.length - 1);
  }
  function goLive() {
    if (!live) { seek(edgeMs); return; }
    mode = 'live'; playing = true; draw(times.length - 1);
  }
  function seek(seconds: number) {
    const t = Math.min(Math.max(0, seconds * 1000), edgeMs);
    if (live && t >= edgeMs - 250) { goLive(); return; }
    mode = 'dvr'; playheadMs = t; lastDrawn = -1;
  }
  function toggle() {
    if (mode === 'live') { mode = 'dvr'; playheadMs = edgeMs; playing = false; return; }
    if (!live && playheadMs >= edgeMs - 50) playheadMs = 0; // replay from the start
    playing = !playing;
  }
  async function fullscreen() {
    if (!shell) return;
    if (document.fullscreenElement) await document.exitFullscreen(); else await shell.requestFullscreen();
  }
  function keydown(event: KeyboardEvent) {
    if ((event.target as HTMLElement).closest('[role="slider"], .menu')) return;
    const key = event.key.toLowerCase();
    if (key === ' ' || key === 'k') toggle();
    else if (key === 'j') seek(currentMs / 1000 - 10);
    else if (key === 'l') seek(currentMs / 1000 + 10);
    else if (key === 'arrowleft') seek(currentMs / 1000 - 5);
    else if (key === 'arrowright') seek(currentMs / 1000 + 5);
    else if (key === 'f') fullscreen();
    else if (key === 'o') overlay = !overlay;
    else if (key === 'c') captionsOn = !captionsOn;
    else if (key === 'r') rotate();
    else return;
    event.preventDefault();
  }

  $effect(() => {
    const ms = currentMs, duration = edgeMs;
    untrack(() => ontime?.(ms, duration));
  });

  onMount(() => { connect(); raf = requestAnimationFrame(tick); });
  onDestroy(() => { closed = true; cancelAnimationFrame(raf); socket?.close(); });
</script>

<!-- Keyboard shortcuts (k, j, l, f, o) live on the focusable player region, like YouTube. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div class="player" bind:this={shell} tabindex="0" role="region" aria-label="Live signing video" onkeydown={keydown}>
  <div class="stage" style:aspect-ratio={aspect} style:width={`min(100%, calc(var(--player-h) * ${aspect}))`}>
    <canvas bind:this={canvas} onclick={toggle}></canvas>
    {#if overlay && canvas}<HolisticOverlay {canvas} frame={frameCount} mirror={false} compact />{/if}
    {#if captionsOn && shownCaption && !discarded}<div class="caption" aria-live="polite">{shownCaption}</div>{/if}
    {#if discarded}
      <div class="notice"><strong>The caller discarded this recording.</strong><span>It has been deleted and will not become a report.</span></div>
    {:else if error && waiting}
      <div class="notice"><strong>{error}</strong></div>
    {:else if waiting}
      <div class="notice"><span class="spinner" aria-hidden="true"></span><span>{connected ? 'Waiting for video…' : 'Connecting…'}</span></div>
    {/if}
  </div>
  {#if !discarded}
    <PlayerControls playing={mode === 'live' || playing} current={currentMs / 1000} duration={edgeMs / 1000} buffered={edgeMs / 1000}
      {rate} {live} atLiveEdge={atEdge} {overlay} captions={captionsOn}
      onplay={toggle} onseek={seek} onrate={(value) => (rate = value)} onoverlay={() => (overlay = !overlay)}
      oncaptions={() => (captionsOn = !captionsOn)} onfullscreen={fullscreen} ongolive={goLive} onrotate={rotate} />
  {/if}
</div>

<style>
  .player{--player-h:min(72vh,640px);position:relative;background:#0b0f12;border-radius:12px;overflow:hidden;display:flex;justify-content:center;outline:none;min-height:260px}
  .player:focus-visible{box-shadow:0 0 0 3px #7fd0e6}
  .player:fullscreen{--player-h:100vh;border-radius:0;align-items:center}
  .stage{position:relative}
  canvas{display:block;width:100%;height:100%;object-fit:contain;cursor:pointer;background:#000}
  .caption{position:absolute;z-index:4;left:50%;bottom:78px;transform:translateX(-50%);max-width:90%;background:#000000c4;color:#fff;font-size:clamp(1rem,2.2vw,1.35rem);font-weight:700;padding:.3rem .7rem;border-radius:6px;text-align:center;text-transform:capitalize}
  .notice{position:absolute;inset:0;z-index:4;display:grid;place-content:center;justify-items:center;gap:.5rem;color:#d4dee2;text-align:center;padding:1rem;background:#0b0f12d0}
  .notice strong{color:#fff}
  .spinner{width:28px;height:28px;border-radius:50%;border:3px solid #ffffff30;border-top-color:#fff;animation:spin .9s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
</style>
