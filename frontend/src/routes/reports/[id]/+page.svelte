<script lang="ts">
  import { page } from '$app/state';
  import { onDestroy, onMount, untrack } from 'svelte';
  import { api, base, FriendlyError } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';
  import { connection } from '$lib/realtime.svelte';
  import { toast } from '$lib/toast.svelte';
  import { localDate, localDateTime, localTime, parseApiTime, relativeTime } from '$lib/time';
  import { categoryLabel, priorityLabel, statusLabel, type History, type LiveStream, type Location, type Related, type Report, type ReportStatus } from '$lib/types';
  import ReportMap from '$lib/components/ReportMap.svelte';
  import LiveVideo from '$lib/components/LiveVideo.svelte';
  import LiveSignPlayer from '$lib/components/LiveSignPlayer.svelte';
  import SignVideoPlayer from '$lib/components/SignVideoPlayer.svelte';
  import CaseActions from '$lib/components/CaseActions.svelte';
  import MotionView from '$lib/components/MotionView.svelte';
  import type { MotionEvent, MotionSample, MotionTrack } from '$lib/motion';
  import Icon from '$lib/components/Icon.svelte';

  type StreamInfo = { active: boolean; requested: boolean; recording: boolean; recording_available: boolean; viewer_url?: string; access_token?: string };
  type SavedVideo = { id: string; label: string; mime_type: string; size: number | null; created_at: string };
  type Reporter = { name: string; email: string; phone: string | null; joined_at: string; last_login_at: string | null; total_reports: number; active_reports: number; resolved_reports: number; reports: Report[] };

  const id = $derived(page.params.id ?? '');
  let report = $state<Report | null>(null);
  let reporter = $state<Reporter | null>(null);
  let location = $state<Location | null>(null);
  let history = $state<History[]>([]);
  let related = $state<Related | null>(null);
  let stream = $state<StreamInfo | null>(null);
  let liveStream = $state<LiveStream | null>(null);
  let videos = $state<SavedVideo[]>([]);
  let videoUrls = $state<Record<string, string>>({});
  let selectedVideo = $state<string | null>(null);
  let loadingVideo = $state(false);
  let error = $state('');
  let busy = $state('');
  let now = $state(Date.now());
  let view = $state<'live' | 'recording' | 'livekit'>('recording');
  // Phone motion recorded with the signing video, kept in step with whichever player is showing.
  let motionSamples = $state.raw<MotionSample[]>([]);
  let motionEvents = $state.raw<MotionEvent[]>([]);
  let playheadMs = $state(0);
  let playDurationMs = $state(0);
  let livePlayer = $state<ReturnType<typeof LiveSignPlayer> | null>(null);
  let videoPlayer = $state<ReturnType<typeof SignVideoPlayer> | null>(null);
  const hasMotion = $derived(motionSamples.length > 0);
  function seekMotion(ms: number) { if (view === 'live') livePlayer?.seekTo(ms); else videoPlayer?.seekTo(ms); }

  const stale = $derived(location ? now - parseApiTime(location.recorded_at).getTime() > 120000 : false);
  const directionUrl = $derived(report ? `https://www.google.com/maps/dir/?api=1&destination=${report.initial_latitude},${report.initial_longitude}` : '#');
  const historyTranscript = $derived.by(() => {
    const item = [...history].reverse().find((entry) => entry.event === 'SIGN_TRANSCRIBED');
    const value = item?.event_metadata.transcript;
    return typeof value === 'string' ? value : '';
  });
  const transcript = $derived(report?.transcript?.trim() || historyTranscript);
  const heading = $derived(report ? report.title?.trim() || categoryLabel(report.category) : '');
  const canRespond = $derived(auth.can('reports.respond'));
  const isMine = $derived(Boolean(report?.assigned_officer && report.assigned_officer.id === auth.profile?.id));
  const closed = $derived(report?.status === 'RESOLVED' || report?.status === 'CANCELLED');

  const steps: { key: ReportStatus; label: string }[] = [
    { key: 'NEW', label: 'Received' },
    { key: 'ACKNOWLEDGED', label: 'Taken' },
    { key: 'RESPONDING', label: 'On the way' },
    { key: 'ARRIVED', label: 'On scene' },
    { key: 'RESOLVED', label: 'Resolved' }
  ];
  const stepIndex = $derived.by(() => {
    if (!report) return 0;
    const status = report.status === 'ASSIGNED' ? 'ACKNOWLEDGED' : report.status;
    return Math.max(0, steps.findIndex((step) => step.key === status));
  });
  const nextAction = $derived.by((): { action: string; label: string; tone?: string } | null => {
    if (!report || !canRespond) return null;
    if (report.status === 'NEW' && !report.assigned_officer) return { action: 'acknowledge', label: 'Take this report' };
    if (!isMine) return null;
    if (report.status === 'ACKNOWLEDGED' || report.status === 'ASSIGNED') return { action: 'respond', label: 'I’m on my way' };
    if (report.status === 'RESPONDING') return { action: 'arrive', label: 'I’ve arrived' };
    if (report.status === 'ARRIVED') return { action: 'resolve', label: 'Resolve report', tone: 'success' };
    return null;
  });

  const eventLabel: Record<string, string> = {
    REPORT_CREATED: 'Report received', OFFICE_ASSIGNED: 'Routed to the responsible office', OFFICER_ACKNOWLEDGED: 'Officer took the report',
    OFFICER_ASSIGNED: 'Officer assigned', OFFICER_UNASSIGNED: 'Returned to the open queue', RESPONDING: 'Officer on the way', ARRIVED: 'Officer on scene',
    RESOLVED: 'Report resolved', PRIORITY_CHANGED: 'Priority changed', STATUS_OVERRIDDEN: 'Status changed by a supervisor', LOCATION_UPDATED: 'Location updated',
    VIDEO_STARTED: 'Live video started', VIDEO_STOPPED: 'Live video stopped', SIGN_TRANSCRIBED: 'Signing video transcribed', SIGN_VIDEO_ATTACHED: 'Signing video attached'
  };
  const timeline = $derived(history.filter((item) => item.event !== 'LOCATION_UPDATED'));

  async function load() {
    try {
      [report, reporter, location, history, related, stream, videos, liveStream] = await Promise.all([
        api<Report>(`/officer/reports/${id}`),
        api<Reporter>(`/officer/reports/${id}/reporter`).catch(() => null),
        api<Location | null>(`/officer/reports/${id}/location`),
        api<History[]>(`/officer/reports/${id}/history`),
        api<Related>(`/officer/reports/${id}/related`).catch(() => null),
        api<StreamInfo>(`/reports/${id}/stream`).catch(() => null),
        api<SavedVideo[]>(`/officer/reports/${id}/videos`),
        api<LiveStream | null>(`/officer/reports/${id}/live`).catch(() => null)
      ]);
      error = '';
      api<MotionTrack | null>(`/officer/reports/${id}/motion`).then((track) => {
        if (track && track.samples.length >= motionSamples.length) { motionSamples = track.samples; motionEvents = track.events; }
      }).catch(() => {});
      try { localStorage.setItem(`report:${id}`, JSON.stringify({ report, location, history, related })); } catch { /* storage unavailable */ }
      chooseView();
    } catch (e) {
      let cached: string | null = null;
      try { cached = localStorage.getItem(`report:${id}`); } catch { /* storage unavailable */ }
      if (cached) ({ report, location, history, related } = JSON.parse(cached));
      else error = e instanceof Error ? e.message : 'This report is unavailable.';
    }
  }
  function chooseView() {
    if (liveStream?.live) view = 'live';
    else if (stream?.active) view = 'livekit';
    else view = 'recording';
    if (!selectedVideo && videos.length) openVideo(videos[0]);
  }

  async function openVideo(video: SavedVideo) {
    selectedVideo = video.id;
    if (videoUrls[video.id]) return;
    loadingVideo = true;
    try {
      const response = await fetch(`${base}/officer/reports/${id}/videos/${video.id}`, { headers: { Authorization: `Bearer ${auth.accessToken}` } });
      if (!response.ok) throw new Error('This video could not be opened.');
      videoUrls = { ...videoUrls, [video.id]: URL.createObjectURL(await response.blob()) };
    } catch (e) { toast.error(e instanceof Error ? e.message : 'This video could not be opened.'); }
    finally { loadingVideo = false; }
  }

  async function action(name: string) {
    busy = name;
    try {
      report = await api<Report>(`/officer/reports/${id}/${name}`, { method: 'POST' });
      toast.success(name === 'acknowledge' ? 'You have taken this report.' : `Marked as ${statusLabel[report.status].toLowerCase()}.`);
      await load();
    } catch (e) { toast.error(e instanceof FriendlyError ? e.message : 'This action could not be completed.'); }
    finally { busy = ''; }
  }
  async function requestVideo() {
    busy = 'video';
    try { stream = await api<StreamInfo>(`/officer/reports/${id}/stream/request`, { method: 'POST' }); toast.success('The caller has been asked to start their camera.'); }
    catch (e) { toast.error(e instanceof Error ? e.message : 'The request could not be sent.'); }
    finally { busy = ''; }
  }
  async function copyRef() {
    if (!report) return;
    try { await navigator.clipboard.writeText(report.reference_code ?? report.public_id); toast.success('Reference copied.'); } catch { /* clipboard unavailable */ }
  }

  onMount(() => {
    load();
    const timer = setInterval(() => {
      now = Date.now();
      api<StreamInfo>(`/reports/${id}/stream`).then((value) => { const started = value.active && !stream?.active; stream = value; if (started && view !== 'live') view = 'livekit'; }).catch(() => {});
      api<SavedVideo[]>(`/officer/reports/${id}/videos`).then((value) => { const fresh = value.length !== videos.length; videos = value; if (fresh && !selectedVideo && value.length) openVideo(value[0]); }).catch(() => {});
      api<Location | null>(`/officer/reports/${id}/location`).then((value) => (location = value)).catch(() => {});
    }, 5000);
    return () => clearInterval(timer);
  });
  $effect(() => {
    const event = connection.lastEvent;
    if (!event) return;
    const mine = event.report_id === id && ['transcription.ready', 'report.updated', 'live.linked'].includes(String(event.type));
    if (mine) untrack(() => load());
  });
  onDestroy(() => Object.values(videoUrls).forEach((url) => URL.revokeObjectURL(url)));
</script>

<svelte:head><title>{heading || 'Report'} · Equal</title></svelte:head>

{#if error && !report}
  <div class="error" role="alert">{error}</div>
{:else if !report}
  <div class="skeleton" style="height:56px;margin-bottom:1rem"></div><div class="skeleton" style="height:420px"></div>
{:else}
  <a class="back" href="/reports"><span class="flip"><Icon name="chevron" size={16} /></span>Report queue</a>

  <header class="report-head">
    <div class="title-block">
      <div class="badges">
        <span class="pill {report.priority.toLowerCase()}">{priorityLabel[report.priority]} priority</span>
        <span class="pill plain status-{report.status.toLowerCase()}">{statusLabel[report.status]}</span>
        {#if liveStream?.live}<span class="pill live-badge">● Signing live</span>{/if}
      </div>
      <h1>{heading}</h1>
      <p class="meta">
        <button class="ref" onclick={copyRef} title="Copy reference">{report.reference_code ?? report.public_id.slice(0, 8)}</button>
        · Received {relativeTime(report.created_at)} · {report.office.name}
        {#if report.reporter_name || reporter}· from <strong>{report.reporter_name || reporter?.name}</strong>{/if}
      </p>
    </div>
    <div class="head-actions">
      <CaseActions {report} onchange={(updated) => { report = updated; load(); }} />
      <a class="button secondary" href={directionUrl} target="_blank" rel="noreferrer"><Icon name="map" size={16} />Directions</a>
      {#if nextAction}<button class="button {nextAction.tone ?? ''}" disabled={!!busy} onclick={() => action(nextAction!.action)}>{busy === nextAction.action ? 'Working…' : nextAction.label}</button>{/if}
    </div>
  </header>

  {#if report.status === 'CANCELLED'}
    <div class="cancelled">This report was cancelled by a supervisor.</div>
  {:else}
    <ol class="stepper" aria-label="Progress">
      {#each steps as step, index (step.key)}
        <li class:done={index < stepIndex || report.status === 'RESOLVED'} class:current={index === stepIndex && report.status !== 'RESOLVED'}>
          <span class="bullet">{#if index < stepIndex || report.status === 'RESOLVED'}<Icon name="check" size={13} />{:else}{index + 1}{/if}</span>
          <span class="step-label">{step.label}</span>
        </li>
      {/each}
    </ol>
  {/if}
  {#if report.assigned_officer}<p class="assignee">Handled by <strong>{report.assigned_officer.name}{isMine ? ' (you)' : ''}</strong></p>{/if}

  <div class="layout">
    <div class="main">
      <section class="panel media" aria-labelledby="video-title">
        <header class="media-head">
          <h2 id="video-title">Signing video</h2>
          <div class="tabs" role="tablist" aria-label="Video source">
            {#if liveStream}<button role="tab" aria-selected={view === 'live'} class:active={view === 'live'} onclick={() => (view = 'live')}>{liveStream.live ? 'Live' : 'Stream replay'}</button>{/if}
            {#if videos.length}<button role="tab" aria-selected={view === 'recording'} class:active={view === 'recording'} onclick={() => (view = 'recording')}>Recording{videos.length > 1 ? `s (${videos.length})` : ''}</button>{/if}
            {#if stream?.active}<button role="tab" aria-selected={view === 'livekit'} class:active={view === 'livekit'} onclick={() => (view = 'livekit')}>Live camera</button>{/if}
          </div>
        </header>

        {#if view === 'live' && liveStream}
          <LiveSignPlayer bind:this={livePlayer} streamId={liveStream.stream_id}
            ontime={(ms, total) => { playheadMs = ms; playDurationMs = total; }}
            onmotion={(batch) => { const last = motionSamples.at(-1)?.t_ms ?? -1; motionSamples = [...motionSamples, ...batch.filter((s) => s.t_ms > last)]; }}
            onmotionevent={(event) => { motionEvents = [...motionEvents, event]; }} />
        {:else if view === 'livekit' && stream?.active && stream.viewer_url && stream.access_token}
          <LiveVideo url={stream.viewer_url} token={stream.access_token} />
        {:else if videos.length && selectedVideo}
          {#if videoUrls[selectedVideo]}
            {@const video = videos.find((item) => item.id === selectedVideo)}
            {#key selectedVideo}<SignVideoPlayer bind:this={videoPlayer} ontime={(ms, total) => { playheadMs = ms; playDurationMs = total; }} src={videoUrls[selectedVideo]} label={video?.label ?? 'Signing video'} downloadName={`${report.reference_code ?? report.public_id}-${selectedVideo}`} />{/key}
          {:else}
            <div class="video-placeholder"><span class="spinner"></span>{loadingVideo ? 'Loading video…' : 'Preparing video…'}</div>
          {/if}
          {#if videos.length > 1}
            <div class="video-list">{#each videos as video (video.id)}<button class:active={selectedVideo === video.id} onclick={() => openVideo(video)}><Icon name="sign" size={15} />{video.label}<small>{localDateTime(video.created_at)}</small></button>{/each}</div>
          {/if}
        {:else}
          <div class="video-placeholder">
            <Icon name="sign" size={30} />
            <p>No signing video for this report yet.</p>
            {#if stream && !stream.active}<button class="button secondary" disabled={busy === 'video' || closed} onclick={requestVideo}>{stream.requested ? 'Request sent — ask again' : 'Ask the caller to go live'}</button>{/if}
          </div>
        {/if}
        {#if hasMotion || (view === 'live' && liveStream?.live)}
          <div class="motion-wrap"><MotionView samples={motionSamples} events={motionEvents} currentMs={playheadMs} durationMs={Math.max(playDurationMs, motionSamples.at(-1)?.t_ms ?? 0)} live={view === 'live' && !!liveStream?.live} onseek={seekMotion} /></div>
        {/if}
        <p class="hint">Tip: press <kbd>o</kbd> for hand and body landmarks, <kbd>j</kbd>/<kbd>l</kbd> to skip 10 s, <kbd>,</kbd>/<kbd>.</kbd> to step frames while paused.</p>
      </section>

      <section class="panel message" id="transcript">
        <p class="eyebrow">What they signed</p>
        {#if transcript}
          <blockquote>{transcript}</blockquote>
          <p class="caveat"><Icon name="info" size={14} />Machine translation from sign language. Confirm anything critical against the video.</p>
        {:else}
          <p class="muted">No transcript was produced. Watch the video above.</p>
        {/if}
        {#if report.labels?.length}<div class="glosses">{#each report.labels as label (label)}<span>{label}</span>{/each}</div>{/if}
      </section>

      <section class="panel">
        <h2>Situation</h2>
        <p class="description">{report.description}</p>
        {#if report.situation_analysis}<h3>Analysis</h3><p class="description">{report.situation_analysis}</p>{/if}
        {#if report.recommended_actions?.length}
          <h3>Recommended actions</h3>
          <ol class="actions-list">{#each report.recommended_actions as item (item)}<li>{item}</li>{/each}</ol>
        {/if}
      </section>

      {#if related && (related.nearby.length || related.same_user.length)}
        <section class="panel">
          <h2>Earlier reports</h2>
          <div class="related-stats"><div><strong>{related.nearby.length}</strong><span>within 10 km</span></div><div><strong>{related.same_user.length}</strong><span>from this caller</span></div><div><strong>{related.same_office.length}</strong><span>this office</span></div></div>
          {#if related.nearby.length}<ul class="link-list">{#each related.nearby.slice(0, 4) as item (item.public_id)}<li><a href={`/reports/${item.public_id}`}><span>{categoryLabel(item.category)}</span><small>{item.distance_km} km · {statusLabel[item.status]} · {localDate(item.created_at)}</small></a></li>{/each}</ul>{/if}
        </section>
      {/if}
    </div>

    <aside class="side">
      <section class="panel map-card">
        <header><h2>{stale ? 'Last known location' : 'Location'}</h2>{#if stale}<span class="pill warn">Not updated recently</span>{:else if location}<span class="pill ok">Live</span>{/if}</header>
        <div class="map-wrap"><ReportMap {report} {location} /></div>
        <p class="muted small">{report.location_label ?? `${report.initial_latitude.toFixed(5)}, ${report.initial_longitude.toFixed(5)}`}{location ? ` · updated ${relativeTime(location.recorded_at)}` : ''}</p>
      </section>

      <section class="panel">
        <h2>Caller</h2>
        {#if reporter}
          <div class="caller"><span class="avatar">{reporter.name.charAt(0)}</span><div><strong>{reporter.name}</strong><small>{reporter.email}</small></div></div>
          <dl>
            <div><dt>Phone</dt><dd>{reporter.phone || 'Not provided'}</dd></div>
            <div><dt>Contact by</dt><dd>Text or video — the caller uses sign language</dd></div>
            <div><dt>Member since</dt><dd>{localDate(reporter.joined_at)}</dd></div>
          </dl>
          <div class="caller-stats"><div><strong>{reporter.total_reports}</strong><span>Reports</span></div><div><strong>{reporter.active_reports}</strong><span>Open</span></div><div><strong>{reporter.resolved_reports}</strong><span>Resolved</span></div></div>
        {:else}<p class="muted">Caller details are unavailable.</p>{/if}
      </section>

      <section class="panel">
        <h2>Timeline</h2>
        {#if timeline.length}
          <ol class="timeline">
            {#each timeline as item, index (index)}
              <li>
                <time title={localDateTime(item.created_at)}>{localTime(item.created_at)}</time>
                <span>{eventLabel[item.event] ?? 'Report updated'}{#if typeof item.event_metadata.to === 'string'} — {item.event_metadata.to}{/if}{#if item.event === 'PRIORITY_CHANGED' && typeof item.event_metadata.new === 'string'} — {item.event_metadata.new.toLowerCase()}{/if}
                  {#if typeof item.event_metadata.reason === 'string' && item.event_metadata.reason}<small>“{item.event_metadata.reason}”</small>{/if}</span>
              </li>
            {/each}
          </ol>
        {:else}<p class="muted">No events yet.</p>{/if}
      </section>
    </aside>
  </div>

  {#if nextAction}
    <div class="mobile-cta"><button class="button {nextAction.tone ?? ''}" disabled={!!busy} onclick={() => action(nextAction!.action)}>{nextAction.label}</button><a class="button secondary" href={directionUrl} target="_blank" rel="noreferrer">Directions</a></div>
  {/if}
{/if}

<style>
  .back{display:inline-flex;align-items:center;gap:.25rem;color:var(--muted);text-decoration:none;font-weight:650;font-size:.88rem;margin-bottom:.9rem}
  .back:hover{color:var(--ink)}.flip{display:inline-flex;transform:scaleX(-1)}
  .report-head{display:flex;justify-content:space-between;align-items:flex-start;gap:1.25rem;flex-wrap:wrap;margin-bottom:1.1rem}
  .title-block{min-width:0;flex:1 1 420px}
  .badges{display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.5rem}
  .live-badge{background:#e5483f;color:#fff}.live-badge::before{display:none}
  h1{margin:0;font-size:clamp(1.45rem,2.6vw,2rem);letter-spacing:-.02em;line-height:1.2}
  .meta{margin:.45rem 0 0;color:var(--muted);font-size:.92rem}
  .ref{border:0;background:var(--surface-2);border:1px solid var(--line);border-radius:6px;padding:.05rem .4rem;font-family:ui-monospace,Menlo,monospace;font-size:.82rem;cursor:pointer;color:var(--ink)}
  .head-actions{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}
  .stepper{list-style:none;margin:0 0 .5rem;padding:0;display:grid;grid-template-columns:repeat(5,1fr);gap:.4rem}
  .stepper li{display:flex;align-items:center;gap:.5rem;padding:.55rem .7rem;border-radius:9px;background:var(--surface);border:1px solid var(--line);color:var(--muted);font-weight:650;font-size:.85rem}
  .stepper .bullet{display:grid;place-items:center;width:22px;height:22px;border-radius:50%;background:var(--surface-2);border:1px solid var(--line-strong);font-size:.72rem;font-weight:800;flex:0 0 auto}
  .stepper li.done{color:#176247;background:var(--green-soft);border-color:#b9dfcf}.stepper li.done .bullet{background:var(--green);border-color:var(--green);color:#fff}
  .stepper li.current{color:var(--navy);border-color:var(--navy);box-shadow:inset 0 0 0 1px var(--navy)}.stepper li.current .bullet{background:var(--navy);border-color:var(--navy);color:#fff}
  .cancelled{background:#eef0f1;border:1px solid var(--line);border-radius:9px;padding:.7rem .9rem;color:var(--ink-2);font-weight:650;margin-bottom:.5rem}
  .assignee{margin:.2rem 0 1.2rem;color:var(--muted);font-size:.9rem}
  .layout{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:1.25rem;align-items:start}
  .main,.side{display:grid;gap:1.25rem;min-width:0}
  .panel h2{font-size:1.02rem;margin:0 0 .8rem}.panel h3{font-size:.85rem;margin:1.1rem 0 .4rem;color:var(--ink-2)}
  .media{padding:1rem}
  .media-head{display:flex;justify-content:space-between;align-items:center;gap:1rem;margin-bottom:.8rem;flex-wrap:wrap}.media-head h2{margin:0}
  .tabs{display:flex;background:var(--surface-2);border:1px solid var(--line);border-radius:9px;padding:3px;gap:2px}
  .tabs button{border:0;background:transparent;padding:.4rem .75rem;border-radius:7px;font-weight:700;color:var(--muted);cursor:pointer;font-size:.85rem}
  .tabs button.active{background:var(--surface);color:var(--ink);box-shadow:var(--shadow)}
  .video-placeholder{display:grid;place-items:center;align-content:center;gap:.7rem;min-height:280px;background:#0b0f12;border-radius:12px;color:#b9c6cc;text-align:center;padding:1.5rem}
  .video-placeholder p{margin:0}
  .spinner{width:28px;height:28px;border-radius:50%;border:3px solid #ffffff30;border-top-color:#fff;animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
  .video-list{display:flex;gap:.5rem;margin-top:.7rem;overflow-x:auto}
  .video-list button{display:grid;grid-template-columns:auto 1fr;column-gap:.4rem;align-items:center;text-align:left;border:1px solid var(--line);background:var(--surface);border-radius:9px;padding:.5rem .7rem;cursor:pointer;font-weight:650;font-size:.85rem;white-space:nowrap}
  .video-list button small{grid-column:2;color:var(--muted);font-weight:500}
  .video-list button.active{border-color:var(--blue);background:var(--blue-soft)}
  .motion-wrap{margin-top:1rem;padding-top:1rem;border-top:1px solid var(--line)}
  .hint{margin:.7rem 0 0;color:var(--muted);font-size:.78rem}
  kbd{font-family:ui-monospace,Menlo,monospace;font-size:.72rem;background:var(--surface-2);border:1px solid var(--line-strong);border-bottom-width:2px;border-radius:4px;padding:0 .3rem}
  .message{border-left:4px solid var(--blue)}
  blockquote{margin:.2rem 0 0;font-size:clamp(1.15rem,2vw,1.45rem);line-height:1.45;font-weight:650;color:var(--ink)}
  .caveat{display:flex;align-items:center;gap:.4rem;color:var(--muted);font-size:.8rem;margin:.8rem 0 0}
  .glosses{display:flex;flex-wrap:wrap;gap:.35rem;margin-top:.8rem}
  .glosses span{font-family:ui-monospace,Menlo,monospace;font-size:.75rem;background:var(--surface-2);border:1px solid var(--line);border-radius:5px;padding:.15rem .45rem;text-transform:uppercase}
  .description{line-height:1.6;color:var(--ink-2);margin:0;white-space:pre-line}
  .actions-list{margin:0;padding-left:1.2rem;display:grid;gap:.35rem;color:var(--ink-2);line-height:1.5}
  .related-stats,.caller-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem}
  .related-stats div,.caller-stats div{background:var(--surface-2);border:1px solid var(--line);border-radius:8px;padding:.6rem;text-align:center}
  .related-stats strong,.caller-stats strong{display:block;font-size:1.25rem;font-variant-numeric:tabular-nums}
  .related-stats span,.caller-stats span{font-size:.72rem;color:var(--muted)}
  .link-list{list-style:none;margin:.8rem 0 0;padding:0}
  .link-list a{display:flex;justify-content:space-between;gap:1rem;padding:.6rem 0;border-top:1px solid var(--line);text-decoration:none}
  .link-list a:hover span{text-decoration:underline}.link-list small{color:var(--muted)}
  .map-card{padding:0;overflow:hidden}
  .map-card header{display:flex;justify-content:space-between;align-items:center;padding:1rem 1rem .7rem}.map-card h2{margin:0}
  .map-wrap{height:250px}.map-card .small{margin:0;padding:.7rem 1rem .9rem}
  .small{font-size:.82rem}
  .caller{display:flex;align-items:center;gap:.7rem;margin-bottom:.4rem}.caller div{display:grid;min-width:0}.caller small{color:var(--muted);overflow:hidden;text-overflow:ellipsis}
  .avatar{display:grid;place-items:center;width:40px;height:40px;border-radius:50%;background:var(--navy);color:#fff;font-weight:800;flex:0 0 auto}
  dl{margin:.6rem 0 .9rem}dl div{display:grid;grid-template-columns:110px 1fr;gap:.6rem;padding:.45rem 0;border-top:1px solid var(--line)}
  dt{font-size:.78rem;color:var(--muted);font-weight:700}dd{margin:0;font-size:.88rem}
  .timeline{list-style:none;margin:0;padding:0}
  .timeline li{display:grid;grid-template-columns:62px 1fr;gap:.5rem;position:relative;padding:.5rem 0 .5rem 1rem;border-left:2px solid #c8d9dd;font-size:.88rem}
  .timeline li::before{content:'';position:absolute;width:9px;height:9px;border-radius:50%;background:var(--blue);left:-5.5px;top:.85rem}
  .timeline time{font-size:.76rem;color:var(--muted);padding-top:.1rem}.timeline small{display:block;color:var(--muted);margin-top:.15rem}
  .status-new{background:#fff3d6;color:#7a4d00}.status-resolved{background:var(--green-soft);color:#176247}.status-cancelled{background:#eef0f1;color:#6b7a80}
  .status-responding,.status-arrived,.status-acknowledged,.status-assigned{background:var(--blue-soft);color:#195a71}
  .mobile-cta{display:none}
  @media(max-width:1100px){.layout{grid-template-columns:1fr}.side{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}}
  @media(max-width:760px){
    .head-actions .button:not(.secondary){display:none}
    .stepper{grid-template-columns:repeat(5,minmax(0,1fr))}.stepper li{flex-direction:column;padding:.5rem .2rem;font-size:.68rem;text-align:center;gap:.3rem}
    .mobile-cta{display:flex;gap:.5rem;position:fixed;z-index:90;left:0;right:0;bottom:calc(58px + env(safe-area-inset-bottom));padding:.6rem .9rem;background:var(--surface);border-top:1px solid var(--line)}
    .mobile-cta .button{flex:1}
    .media{padding:.6rem}
  }
</style>
