<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { page } from '$app/state';
  import { api, errorMessage } from '$lib/api/client';
  import { connection } from '$lib/realtime.svelte';
  import { localDateTime, relativeTime } from '$lib/time';
  import type { LiveStream } from '$lib/types';
  import Icon from '$lib/components/Icon.svelte';
  import LiveSignPlayer from '$lib/components/LiveSignPlayer.svelte';
  import MotionView from '$lib/components/MotionView.svelte';
  import type { MotionEvent, MotionSample, MotionTrack } from '$lib/motion';
  import RequirePermission from '$lib/components/RequirePermission.svelte';

  const id = $derived(page.params.id ?? '');
  let info = $state<LiveStream | null>(null);
  let error = $state('');
  let caption = $state('');
  let transcript = $state('');
  let discarded = $state(false);
  let samples = $state.raw<MotionSample[]>([]);
  let events = $state.raw<MotionEvent[]>([]);
  let playheadMs = $state(0);
  let durationMs = $state(0);
  let player = $state<ReturnType<typeof LiveSignPlayer> | null>(null);

  async function loadMotion() {
    try {
      const track = await api<MotionTrack>(`/officer/live/${id}/motion`);
      // Live samples may already have arrived over the socket; keep whichever is longer.
      if (track.samples.length >= samples.length) { samples = track.samples; events = track.events; }
    } catch { /* the view just shows "waiting" */ }
  }

  async function load() {
    try { info = await api<LiveStream>(`/officer/live/${id}`); error = ''; }
    catch (e) { error = errorMessage(e, 'This stream is no longer available.'); }
  }
  onMount(() => { load(); loadMotion(); });
  $effect(() => {
    const event = connection.lastEvent;
    if (event && typeof event.type === 'string' && event.type.startsWith('live.') && event.stream_id === id) untrack(() => load());
  });
</script>

<svelte:head><title>{info?.live ? 'Live signing' : 'Stream replay'} · Equal</title></svelte:head>
<RequirePermission permission="reports.view">
  <a class="back" href="/dashboard"><span class="flip"><Icon name="chevron" size={16} /></span>Overview</a>
  {#if error && !info}
    <div class="empty"><p>{error}</p><a class="button secondary" href="/dashboard">Back to overview</a></div>
  {:else}
    <header class="head">
      <div>
        <p class="eyebrow">{discarded ? 'Discarded' : info?.live ? 'Signing live now' : info?.report_id ? 'Filed as a report' : 'Draft — not filed yet'}</p>
        <h1>{info?.reporter_name ?? 'Equal app caller'}</h1>
        {#if info}<p class="muted">Started {relativeTime(info.started_at)} · {localDateTime(info.started_at)}</p>{/if}
      </div>
      {#if info?.report_id}<a class="button" href={`/reports/${info.report_id}`}>Open the report<Icon name="chevron" size={16} /></a>{/if}
    </header>
    <div class="layout">
      <LiveSignPlayer bind:this={player} streamId={id}
        onstate={(state) => { caption = state.caption; transcript = state.transcript; discarded = state.discarded; }}
        ontime={(ms, total) => { playheadMs = ms; durationMs = total; }}
        onmotion={(batch) => { const last = samples.at(-1)?.t_ms ?? -1; samples = [...samples, ...batch.filter((s) => s.t_ms > last)]; }}
        onmotionevent={(event) => { events = [...events, event]; }} />
      <aside class="side">
      <section class="panel">
        <p class="eyebrow">Live translation</p>
        {#if transcript || caption}
          <p class="transcript">{transcript || caption}</p>
          {#if caption && transcript}<p class="muted small">Latest sign: <strong>{caption}</strong></p>{/if}
        {:else}<p class="muted">Recognised signs appear here as the caller signs.</p>{/if}
        <p class="caveat"><Icon name="info" size={14} />Machine translation; watch the video for anything critical. The report arrives when the caller sends it — this draft is deleted if they discard it.</p>
      </section>
      {#if !discarded}
        <section class="panel"><MotionView {samples} {events} currentMs={playheadMs} {durationMs} live={info?.live ?? false} onseek={(ms) => player?.seekTo(ms)} /></section>
      {/if}
      </aside>
    </div>
  {/if}
</RequirePermission>

<style>
  .back{display:inline-flex;align-items:center;gap:.25rem;color:var(--muted);text-decoration:none;font-weight:650;font-size:.88rem;margin-bottom:.9rem}.flip{display:inline-flex;transform:scaleX(-1)}
  .head{display:flex;justify-content:space-between;align-items:flex-end;gap:1rem;flex-wrap:wrap;margin-bottom:1.1rem}
  h1{margin:0;font-size:clamp(1.4rem,2.6vw,1.9rem)}.head p{margin:.3rem 0 0}
  .layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(320px,400px);gap:1.25rem;align-items:start}
  .side{display:grid;gap:1rem}
  .transcript{font-size:1.3rem;font-weight:650;line-height:1.45;margin:.3rem 0;text-transform:capitalize}
  .caveat{display:flex;gap:.4rem;color:var(--muted);font-size:.8rem;line-height:1.45;margin:1rem 0 0}.small{font-size:.85rem}
  .empty{display:grid;justify-items:center;gap:.8rem}
  @media(max-width:1000px){.layout{grid-template-columns:1fr}}
</style>
