<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { api, FriendlyError } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';
  import { connection } from '$lib/realtime.svelte';
  import { toast } from '$lib/toast.svelte';
  import SignTranscriber from '$lib/components/SignTranscriber.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import { parseApiTime, relativeTime } from '$lib/time';
  import { categoryLabel, priorityLabel, statusLabel, type LiveStream, type Report, type ReportsPage } from '$lib/types';

  let reports = $state<Report[]>([]); let loading = $state(true); let error = $state(''); let taking = $state('');
  let scope = $state<'office' | 'all'>('office'); let allowAll = $state(true); let showAll = $state(false);
  let transcriberOpen = $state(false);
  // Callers signing right now, and recordings not filed yet (drafts). Filed ones link to their report.
  let streams = $state<LiveStream[]>([]);
  const liveNow = $derived(streams.filter((s) => s.live));
  const drafts = $derived(streams.filter((s) => !s.live && !s.report_id));
  async function loadStreams() { try { streams = await api<LiveStream[]>('/officer/live'); } catch { /* panel just stays empty */ } }
  let loadingRequest: Promise<void> | null = null;

  const open = $derived(reports.filter((r) => r.status !== 'RESOLVED' && r.status !== 'CANCELLED'));
  const rank = { CRITICAL: 0, HIGH: 1, NORMAL: 2 } as const;
  // Unclaimed and urgent first, then oldest first: the order someone should pick them up in.
  const attention = $derived(
    [...open].sort((a, b) => Number(!!a.assigned_officer) - Number(!!b.assigned_officer) || rank[a.priority] - rank[b.priority] || parseApiTime(a.created_at).getTime() - parseApiTime(b.created_at).getTime())
  );
  const LIMIT = 8;
  const visible = $derived(showAll ? attention : attention.slice(0, LIMIT));
  const mine = $derived(open.filter((r) => r.assigned_officer && r.assigned_officer.id === auth.profile?.id));
  const unclaimed = $derived(open.filter((r) => !r.assigned_officer).length);
  const urgent = $derived(open.filter((r) => r.priority !== 'NORMAL').length);
  const responding = $derived(open.filter((r) => r.status === 'RESPONDING' || r.status === 'ARRIVED').length);
  const resolvedToday = $derived(reports.filter((r) => r.status === 'RESOLVED' && r.resolved_at && parseApiTime(r.resolved_at).toDateString() === new Date().toDateString()).length);
  const byOffice = $derived.by(() => {
    const counts = new Map<string, number>();
    for (const r of open) counts.set(r.office.name, (counts.get(r.office.name) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  });
  const officeMax = $derived(Math.max(1, ...byOffice.map(([, n]) => n)));
  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  const canRespond = $derived(auth.can('reports.respond'));
  // Demo accounts are named after their role; don't greet someone as "Super".
  const firstName = $derived(auth.name && !/admin|auditor|dispatcher|officer/i.test(auth.name) ? auth.name.split(' ')[0] : null);

  async function load(): Promise<void> {
    if (loadingRequest) return loadingRequest;
    const requested = scope;
    loadingRequest = (async (): Promise<void> => {
      loading = true;
      try {
        const page = await api<ReportsPage>(`/officer/reports?page_size=100&scope=${requested}`);
        reports = page.items; error = '';
        try { localStorage.setItem(`cached_reports_${requested}`, JSON.stringify(reports)); } catch { /* storage full or blocked */ }
      } catch (e) {
        if (e instanceof FriendlyError && e.status === 403 && requested === 'all') { allowAll = false; scope = 'office'; loadingRequest = null; return load(); }
        let cached: string | null = null;
        try { cached = localStorage.getItem(`cached_reports_${requested}`); } catch { /* storage blocked */ }
        if (cached) reports = JSON.parse(cached); else error = e instanceof Error ? e.message : 'Reports are unavailable.';
      } finally { loading = false; loadingRequest = null; }
    })();
    return loadingRequest;
  }
  async function setScope(value: 'office' | 'all') { if (scope === value) return; if (loadingRequest) await loadingRequest; scope = value; await load(); }
  async function takeReport(report: Report) {
    taking = report.public_id;
    try {
      const updated = await api<Report>(`/officer/reports/${report.public_id}/acknowledge`, { method: 'POST' });
      reports = reports.map((item) => item.public_id === updated.public_id ? updated : item);
      toast.success(`You have taken the ${updated.category} report.`);
    } catch (e) { toast.error(e instanceof FriendlyError ? e.message : 'This report could not be taken.'); await load(); }
    finally { taking = ''; }
  }
  onMount(() => { load(); loadStreams(); });
  $effect(() => {
    const type = connection.lastEvent?.type;
    if (!type || type === 'connected') return;
    // Only the event is a dependency; reloading and toasting must not subscribe this effect.
    untrack(() => {
      if (typeof type === 'string' && type.startsWith('live.')) {
        loadStreams();
        if (type === 'live.started') toast.show('Someone has started signing in the Equal app.', 'info');
      } else load();
    });
  });
</script>

<svelte:head><title>Overview · Equal</title></svelte:head>
<header class="hero">
  <div>
    <p class="eyebrow">{auth.roleLabel}{auth.office ? ` · ${auth.office}` : ''}</p>
    <h1>{greeting}{firstName ? `, ${firstName}` : ''}</h1>
    <p class="sub">
      <span class="live" class:off={!connection.connected}>{connection.connected ? 'Live' : 'Connecting…'}</span>
      {scope === 'all' ? 'Showing every office' : `Reports routed to ${auth.office || 'your offices'}`}
    </p>
  </div>
  {#if allowAll}
    <div class="segmented" role="group" aria-label="Report source"><button class:on={scope === 'office'} aria-pressed={scope === 'office'} onclick={() => setScope('office')}>My offices</button><button class:on={scope === 'all'} aria-pressed={scope === 'all'} onclick={() => setScope('all')}>All offices</button></div>
  {/if}
</header>

{#if liveNow.length || drafts.length}
  <section class="panel live-panel" aria-labelledby="live-title">
    <header class="panel-head">
      <div><h2 id="live-title"><span class="rec"></span>Live & drafts</h2><p>Recordings appear the moment a caller starts signing — before they send the report.</p></div>
    </header>
    <ul class="streams">
      {#each [...liveNow, ...drafts] as s (s.stream_id)}
        <li>
          <a href={`/live/${s.stream_id}`}>
            {#if s.live}<span class="tag live">LIVE</span>{:else}<span class="tag draft">Draft</span>{/if}
            <span class="who"><strong>{s.reporter_name ?? 'Equal app caller'}</strong><small>{s.live ? `Signing for ${Math.round(s.duration_ms / 1000)} s` : `Stopped ${relativeTime(s.ended_at ?? s.started_at)} · not sent yet`}{s.caption ? ` · “${s.caption}”` : ''}</small></span>
            <span class="button small {s.live ? '' : 'secondary'}">{s.live ? 'Watch live' : 'Replay'}</span>
          </a>
        </li>
      {/each}
    </ul>
  </section>
{/if}

<section class="stats" aria-label="Report summary">
  <a class="stat" class:alert={unclaimed > 0} href="/reports"><span>Waiting for an officer</span><strong>{unclaimed}</strong></a>
  <div class="stat" class:alert={urgent > 0}><span>High or critical</span><strong>{urgent}</strong></div>
  <div class="stat"><span>Officers on the way</span><strong>{responding}</strong></div>
  <a class="stat" href="/history"><span>Resolved today</span><strong>{resolvedToday}</strong></a>
</section>

<div class="layout">
  <section class="panel queue" aria-labelledby="attention-title">
    <header class="panel-head">
      <div><h2 id="attention-title">Needs attention</h2><p>Unclaimed and most urgent first</p></div>
      <a class="button ghost small" href="/reports">Full queue <Icon name="chevron" size={15} /></a>
    </header>
    {#if error}<div class="error" role="alert">{error}</div>{/if}
    {#if loading && !reports.length}
      <div class="rows">{#each Array(4) as _, i (i)}<div class="skeleton row-skeleton"></div>{/each}</div>
    {:else if visible.length}
      <ul class="rows">
        {#each visible as report (report.public_id)}
          {@const available = report.status === 'NEW' && !report.assigned_officer}
          <li class="row {report.priority.toLowerCase()}">
            <a class="row-main" href={`/reports/${report.public_id}`}>
              <span class="row-top">
                <span class="pill {report.priority.toLowerCase()}">{priorityLabel[report.priority]}</span>
                <strong>{report.title || categoryLabel(report.category)}</strong>
              </span>
              <span class="desc">{report.description}</span>
              <span class="meta">
                {report.office.name} · {relativeTime(report.created_at)} ·
                {#if available}<em class="waiting">Waiting for an officer</em>{:else}{statusLabel[report.status]}{report.assigned_officer ? ` — ${report.assigned_officer.name}` : ''}{/if}
              </span>
            </a>
            <div class="row-actions">
              {#if available && canRespond}
                <button class="button small" disabled={taking === report.public_id} onclick={() => takeReport(report)}>{taking === report.public_id ? 'Taking…' : 'Take report'}</button>
              {:else}
                <a class="button secondary small" href={`/reports/${report.public_id}`}>Open</a>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
      {#if attention.length > LIMIT}
        <button class="show-more" onclick={() => showAll = !showAll}>{showAll ? 'Show fewer' : `Show ${attention.length - LIMIT} more`}</button>
      {/if}
    {:else}
      <div class="calm"><Icon name="check" size={28} /><p><strong>All clear.</strong> No open reports{scope === 'office' && auth.office ? ` for ${auth.office}` : ''}. New ones appear here instantly.</p></div>
    {/if}
  </section>

  <aside class="rail">
    {#if canRespond}
      <section class="panel">
        <h2>Your active reports</h2>
        {#if mine.length}
          <ul class="mine">{#each mine as report (report.public_id)}<li><a href={`/reports/${report.public_id}`}><span class="dot {report.priority.toLowerCase()}"></span><span class="mine-text"><strong>{report.title || categoryLabel(report.category)}</strong><small>{statusLabel[report.status]} · {relativeTime(report.created_at)}</small></span><Icon name="chevron" size={16} /></a></li>{/each}</ul>
        {:else}<p class="muted">Nothing assigned to you right now.</p>{/if}
      </section>
    {/if}

    {#if byOffice.length > 1}
      <section class="panel">
        <h2>Open by office</h2>
        <ul class="offices">
          {#each byOffice as [name, count] (name)}
            <li><span class="office-name">{name}</span><span class="track"><span style:width={`${(count / officeMax) * 100}%`}></span></span><b>{count}</b></li>
          {/each}
        </ul>
      </section>
    {/if}

    <section class="panel tool">
      <h2><Icon name="sign" />Sign transcriber</h2>
      <p class="muted">Record someone signing in front of you and get a rough English transcript.</p>
      <button class="button secondary" onclick={() => transcriberOpen = !transcriberOpen} aria-expanded={transcriberOpen}>{transcriberOpen ? 'Close transcriber' : 'Open transcriber'}</button>
    </section>
  </aside>
</div>

{#if transcriberOpen}<section class="panel transcriber"><SignTranscriber /></section>{/if}

<style>
  .hero{display:flex;justify-content:space-between;align-items:flex-end;gap:1.5rem;flex-wrap:wrap;margin-bottom:1.75rem}
  .hero h1{margin:.1rem 0 0;font-size:clamp(1.6rem,2.8vw,2.1rem);letter-spacing:-.02em}
  .sub{margin:.45rem 0 0;color:var(--muted);display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}
  .live{display:inline-flex;align-items:center;gap:.35rem;font-size:.75rem;font-weight:800;color:var(--green);background:var(--green-soft);padding:.15rem .55rem;border-radius:999px}
  .live::before{content:'';width:7px;height:7px;border-radius:50%;background:currentColor}
  .live.off{color:#8a5100;background:var(--amber-soft)}
  .segmented{display:flex;border:1px solid var(--line-strong);border-radius:9px;overflow:hidden;background:var(--surface)}
  .segmented button{border:0;background:transparent;padding:.55rem .95rem;font-weight:700;color:var(--ink-2);cursor:pointer}
  .segmented button.on{background:var(--navy);color:#fff}

  .stats{grid-template-columns:repeat(4,minmax(0,1fr));gap:1rem;margin-bottom:1.75rem}
  .stat{padding:1.1rem 1.25rem;gap:.35rem}
  .stat strong{font-size:2.1rem;line-height:1}

  .layout{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:1.5rem;align-items:start}
  .panel h2{font-size:1rem;margin:0 0 .75rem;display:flex;align-items:center;gap:.5rem}
  .panel-head{display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;margin-bottom:.5rem}
  .panel-head h2{margin:0}.panel-head p{margin:.2rem 0 0;color:var(--muted);font-size:.85rem}
  .queue{padding:1.25rem 1.25rem 0;overflow:hidden}

  .rows{list-style:none;margin:0 -1.25rem;padding:0;display:grid}
  .row{display:flex;align-items:center;gap:1.25rem;padding:1rem 1.25rem;border-top:1px solid var(--line);position:relative}
  .row::before{content:'';position:absolute;left:0;top:.9rem;bottom:.9rem;width:3px;border-radius:0 3px 3px 0;background:var(--blue)}
  .row.high::before{background:var(--amber)}.row.critical::before{background:var(--red)}
  .row:hover{background:#f8fafb}
  .row-main{flex:1;min-width:0;display:grid;gap:.3rem;text-decoration:none}
  .row-top{display:flex;align-items:center;gap:.6rem}.row-top strong{font-size:1rem}
  .row-main:hover strong{text-decoration:underline}
  .desc{color:var(--ink-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:.92rem}
  .meta{color:var(--muted);font-size:.82rem}
  .waiting{font-style:normal;font-weight:700;color:#176247}
  .row-actions{flex:0 0 auto}
  .row-skeleton{height:84px;border-radius:0;margin:0 1.25rem 1px}
  .show-more{display:block;width:calc(100% + 2.5rem);margin:0 -1.25rem;padding:.85rem;border:0;border-top:1px solid var(--line);background:transparent;font-weight:700;color:var(--blue);cursor:pointer}
  .show-more:hover{background:#f8fafb}
  .calm{display:grid;justify-items:center;text-align:center;gap:.5rem;padding:3rem 1rem;color:var(--muted)}.calm :global(svg){color:var(--green)}.calm p{margin:0;max-width:36ch;line-height:1.5}

  .live-panel{margin-bottom:1.5rem;border-color:#f1c6c3;padding:1.1rem 1.25rem .4rem}
  .live-panel h2{display:flex;align-items:center;gap:.5rem}
  .rec{width:10px;height:10px;border-radius:50%;background:#e5483f;box-shadow:0 0 0 4px #e5483f26;animation:blink 1.4s infinite}
  @keyframes blink{50%{opacity:.35}}
  .streams{list-style:none;margin:.4rem -1.25rem 0;padding:0}
  .streams a{display:flex;align-items:center;gap:.9rem;padding:.8rem 1.25rem;border-top:1px solid var(--line);text-decoration:none}
  .streams a:hover{background:#fbf6f5}
  .streams .who{flex:1;display:grid;min-width:0}.streams small{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .tag{font-size:.7rem;font-weight:900;letter-spacing:.06em;border-radius:5px;padding:.2rem .45rem}
  .tag.live{background:#e5483f;color:#fff}.tag.draft{background:#eef0f1;color:#55646a}
  .rail{display:grid;gap:1.25rem}
  .mine{list-style:none;margin:0;padding:0}
  .mine a{display:flex;align-items:center;gap:.7rem;padding:.65rem 0;border-top:1px solid var(--line);text-decoration:none}
  .mine li:first-child a{border-top:0;padding-top:0}
  .mine-text{flex:1;display:grid}.mine-text small{color:var(--muted)}.mine a:hover strong{text-decoration:underline}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--blue);flex:0 0 auto}.dot.high{background:var(--amber)}.dot.critical{background:var(--red)}
  .offices{list-style:none;margin:0;padding:0;display:grid;gap:.85rem}
  .offices li{display:grid;grid-template-columns:1fr auto;align-items:center;gap:.35rem .6rem;font-size:.86rem}.offices .track{grid-column:1/-1;grid-row:2}
  .office-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--ink-2)}
  .track{height:8px;background:var(--surface-2);border-radius:4px;overflow:hidden}.track span{display:block;height:100%;background:#2a78d6;border-radius:0 4px 4px 0}
  .offices b{text-align:right;font-variant-numeric:tabular-nums}
  .tool p{margin:0 0 .9rem;line-height:1.5;font-size:.9rem}
  .transcriber{margin-top:1.5rem}

  @media(max-width:1100px){.layout{grid-template-columns:1fr}.rail{grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}}
  @media(max-width:760px){
    .stats{grid-template-columns:1fr 1fr;gap:.7rem}.stat strong{font-size:1.7rem}
    .segmented{width:100%}.segmented button{flex:1}
    .row{flex-direction:column;align-items:stretch;gap:.7rem}.row-actions .button{width:100%}
    .desc{white-space:normal;display:-webkit-box;-webkit-line-clamp:2;line-clamp:2;-webkit-box-orient:vertical}
  }
</style>
