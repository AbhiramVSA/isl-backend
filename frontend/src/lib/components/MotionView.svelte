<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import * as THREE from 'three';
  import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
  import { estimatePath, indexAt, intensity, intensityLabel, quatToThree, rotate, tilt, toThree, type MotionEvent, type MotionSample } from '$lib/motion';

  /**
   * The caller's phone in 3D, following the video playhead.
   *
   * Orientation (default): a phone model turned exactly as the real one was,
   * and a trail on a sphere showing where its screen faced over the last few
   * seconds, darker-to-lighter by how hard it was moving. Path: a dead-reckoned
   * route through space — approximate, and labelled as such.
   */
  let {
    samples,
    events = [],
    currentMs,
    durationMs,
    live = false,
    onseek
  }: {
    samples: MotionSample[];
    events?: MotionEvent[];
    currentMs: number;
    durationMs: number;
    live?: boolean;
    onseek?: (ms: number) => void;
  } = $props();

  const TRAIL_MS = 12000;
  // Sequential blue ramp, steps chosen to read on the dark stage: dim = calm, bright = vigorous.
  const RAMP = ['#184f95', '#256abf', '#3987e5', '#6da7ec', '#9ec5f4', '#cde2fb'].map((hex) => new THREE.Color(hex));
  const STATUS: Record<MotionEvent['kind'], string> = { impact: '#e5483f', shaking: '#eda100', jolt: '#eda100' };

  let mode = $state<'orientation' | 'path'>('orientation');
  let host = $state<HTMLDivElement | null>(null);
  let strip = $state<HTMLCanvasElement | null>(null);
  let renderer: THREE.WebGLRenderer | null = null;
  let scene: THREE.Scene, camera: THREE.PerspectiveCamera, controls: OrbitControls;
  let phone: THREE.Group, trail: THREE.Line, pathLine: THREE.Line, dot: THREE.Mesh, orientationRig: THREE.Group, pathRig: THREE.Group, grid: THREE.GridHelper;
  let eventMarkers: THREE.Group;
  let raf = 0;
  let resize: ResizeObserver | null = null;
  let pathCache: { length: number; points: [number, number, number][] } = { length: 0, points: [] };
  let webglFailed = $state(false);
  // Geometry is rebuilt only when the playhead lands on a different sample.
  let drawnKey = '';
  let lastMode = 'orientation';
  let markerCount = -1;
  const markerGeometry = new THREE.SphereGeometry(0.045, 14, 10);

  const index = $derived(indexAt(samples, currentMs));
  const sample = $derived(index >= 0 ? samples[index] : null);
  const now = $derived(sample ? intensity(sample) : 0);
  const angles = $derived(sample ? tilt(sample.q) : null);
  const recentEvents = $derived(events.filter((event) => event.t_ms <= currentMs).slice(-3).reverse());

  function rampColor(value: number) {
    const x = Math.min(1, value / 8) * (RAMP.length - 1);
    const i = Math.floor(x);
    return RAMP[i].clone().lerp(RAMP[Math.min(RAMP.length - 1, i + 1)], x - i);
  }

  function buildPhone() {
    const group = new THREE.Group();
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(0.36, 0.72, 0.05),
      new THREE.MeshStandardMaterial({ color: 0x1c2a33, roughness: 0.5, metalness: 0.3 })
    );
    const screen = new THREE.Mesh(
      new THREE.PlaneGeometry(0.32, 0.64),
      new THREE.MeshStandardMaterial({ color: 0x2a78d6, emissive: 0x123a66, roughness: 0.3 })
    );
    screen.position.z = 0.026;
    const lens = new THREE.Mesh(new THREE.CircleGeometry(0.025, 20), new THREE.MeshBasicMaterial({ color: 0xffffff }));
    lens.position.set(0, 0.31, 0.027);
    // A small arrow out of the screen: the way the front camera (and the caller) faced.
    const facing = new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, 0, 0.03), 0.45, 0x7fd0e6, 0.09, 0.06);
    group.add(body, screen, lens, facing);
    return group;
  }

  function init() {
    if (!host) return;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      webglFailed = true;
      return;
    }
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    renderer.setClearColor(0x0b0f12);
    host.appendChild(renderer.domElement);
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(45, 1, 0.01, 200);
    camera.position.set(1.8, 1.3, 2.2);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.enablePan = false;
    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const light = new THREE.DirectionalLight(0xffffff, 1.4);
    light.position.set(2, 3, 2);
    scene.add(light);

    orientationRig = new THREE.Group();
    const sphere = new THREE.LineSegments(
      new THREE.WireframeGeometry(new THREE.SphereGeometry(1, 18, 12)),
      new THREE.LineBasicMaterial({ color: 0x2b3a42, transparent: true, opacity: 0.55 })
    );
    const horizon = new THREE.Mesh(
      new THREE.RingGeometry(0.995, 1.01, 64),
      new THREE.MeshBasicMaterial({ color: 0x55666e, side: THREE.DoubleSide })
    );
    horizon.rotation.x = -Math.PI / 2;
    phone = buildPhone();
    trail = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ vertexColors: true }));
    eventMarkers = new THREE.Group();
    orientationRig.add(sphere, horizon, phone, trail, eventMarkers, compass());
    scene.add(orientationRig);

    pathRig = new THREE.Group();
    grid = new THREE.GridHelper(4, 16, 0x3a4a52, 0x1f2a30);
    pathLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ vertexColors: true }));
    dot = new THREE.Mesh(new THREE.SphereGeometry(0.06, 20, 14), new THREE.MeshStandardMaterial({ color: 0xe5483f, emissive: 0x551510 }));
    pathRig.add(grid, pathLine, dot);
    pathRig.visible = false;
    scene.add(pathRig);

    resize = new ResizeObserver(fit);
    resize.observe(host);
    fit();
    raf = requestAnimationFrame(frame);
  }

  function compass() {
    // "N" on the horizon so a responder can tell which way the caller faced.
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 64;
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = '#9fb3bb'; ctx.font = 'bold 40px Inter, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('N', 32, 34);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true }));
    sprite.scale.set(0.16, 0.16, 1);
    sprite.position.set(...toThree([0, 1.12, 0]));
    return sprite;
  }

  function fit() {
    if (!host || !renderer) return;
    const width = host.clientWidth, height = host.clientHeight;
    renderer.setSize(width, height, false);
    camera.aspect = width / Math.max(1, height);
    camera.updateProjectionMatrix();
  }

  function updateOrientation() {
    if (!sample) { phone.visible = false; return; }
    phone.visible = true;
    const [x, y, z, w] = quatToThree(sample.q);
    phone.quaternion.set(x, y, z, w);

    const from = currentMs - TRAIL_MS;
    const start = Math.max(0, indexAt(samples, from));
    const positions: number[] = [];
    const colors: number[] = [];
    for (let i = start; i <= index; i++) {
      const s = samples[i];
      const facing = toThree(rotate(s.q, [0, 0, 1]));
      positions.push(...facing);
      const c = rampColor(intensity(s));
      // Older points fade toward the background.
      const age = 1 - (currentMs - s.t_ms) / TRAIL_MS;
      colors.push(c.r * (0.25 + 0.75 * age), c.g * (0.25 + 0.75 * age), c.b * (0.25 + 0.75 * age));
    }
    trail.geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    trail.geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    trail.geometry.computeBoundingSphere();

    if (markerCount !== events.length) {
      eventMarkers.children.forEach((child) => ((child as THREE.Mesh).material as THREE.Material).dispose());
      eventMarkers.clear();
      for (const event of events) {
        const s = samples[Math.max(0, indexAt(samples, event.t_ms))];
        const marker = new THREE.Mesh(markerGeometry, new THREE.MeshBasicMaterial({ color: STATUS[event.kind] }));
        if (s) marker.position.set(...toThree(rotate(s.q, [0, 0, 1])));
        marker.userData.t = event.t_ms;
        eventMarkers.add(marker);
      }
      markerCount = events.length;
    }
    for (const marker of eventMarkers.children) marker.visible = marker.userData.t <= currentMs && marker.userData.t >= from;
  }

  function updatePath() {
    if (pathCache.length !== samples.length) pathCache = { length: samples.length, points: estimatePath(samples) };
    const points = pathCache.points;
    if (!points.length || index < 0) { dot.visible = false; return; }
    dot.visible = true;
    const positions: number[] = [];
    const colors: number[] = [];
    for (let i = 0; i <= index; i++) {
      positions.push(...points[i]);
      const c = rampColor(intensity(samples[i]));
      colors.push(c.r, c.g, c.b);
    }
    pathLine.geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    pathLine.geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    pathLine.geometry.computeBoundingSphere();
    dot.position.set(...points[index]);
    // Keep the whole path in view; the grid follows its scale.
    const extent = Math.max(0.5, ...points.slice(0, index + 1).map((p) => Math.max(Math.abs(p[0]), Math.abs(p[2]), Math.abs(p[1]))));
    grid.scale.setScalar(Math.max(0.5, extent / 1.5));
    pathTarget.set(...points[index]);
    // Frame the path once when entering this mode (and when it outgrows the view);
    // after that the responder's own camera moves are left alone.
    if (framedExtent === 0 || extent > framedExtent * 1.6) {
      framedExtent = extent;
      camera.position.set(pathTarget.x + extent * 1.8, pathTarget.y + extent * 1.2, pathTarget.z + extent * 1.8);
    }
  }
  let framedExtent = 0;
  const pathTarget = new THREE.Vector3();

  function frame() {
    if (!renderer) return;
    if (mode !== lastMode) {
      lastMode = mode;
      framedExtent = 0;
      if (mode === 'orientation') camera.position.set(1.8, 1.3, 2.2);
    }
    orientationRig.visible = mode === 'orientation';
    pathRig.visible = mode === 'path';
    const key = `${mode}:${index}:${samples.length}:${events.length}`;
    if (key !== drawnKey) {
      drawnKey = key;
      if (mode === 'orientation') updateOrientation(); else updatePath();
    }
    if (mode === 'orientation') controls.target.set(0, 0, 0);
    if (mode === 'path') controls.target.lerp(pathTarget, 0.08);
    controls.update();
    renderer.render(scene, camera);
    drawStrip();
    raf = requestAnimationFrame(frame);
  }

  /** Intensity over the whole recording, with events and the playhead; click to seek. */
  function drawStrip() {
    if (!strip) return;
    const width = strip.clientWidth, height = strip.clientHeight;
    const ratio = Math.min(2, window.devicePixelRatio);
    if (strip.width !== width * ratio) { strip.width = width * ratio; strip.height = height * ratio; }
    const ctx = strip.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const span = Math.max(1, durationMs);
    const x = (t: number) => (t / span) * width;
    ctx.strokeStyle = '#3987e5';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    const step = Math.max(1, Math.floor(samples.length / width));
    for (let i = 0; i < samples.length; i += step) {
      const y = height - 4 - Math.min(1, intensity(samples[i]) / 8) * (height - 10);
      if (i === 0) ctx.moveTo(x(samples[i].t_ms), y); else ctx.lineTo(x(samples[i].t_ms), y);
    }
    ctx.stroke();
    for (const event of events) {
      ctx.fillStyle = STATUS[event.kind];
      ctx.beginPath(); ctx.arc(x(event.t_ms), 6, 4, 0, Math.PI * 2); ctx.fill();
    }
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(Math.min(width - 2, x(currentMs)), 0, 2, height);
  }
  function stripClick(event: MouseEvent) {
    if (!strip || !onseek) return;
    const rect = strip.getBoundingClientRect();
    onseek(((event.clientX - rect.left) / rect.width) * Math.max(1, durationMs));
  }

  const formatTime = (ms: number) => { const s = Math.max(0, Math.round(ms / 1000)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };

  onMount(init);
  onDestroy(() => {
    cancelAnimationFrame(raf);
    resize?.disconnect();
    controls?.dispose();
    renderer?.dispose();
    renderer?.domElement.remove();
  });
</script>

<section class="motion" aria-label="Phone motion">
  <header>
    <div>
      <h3>Phone motion</h3>
      <p>{samples.length ? `${intensityLabel(now)}${angles ? ` · tilted ${angles.pitch}° / ${angles.roll}°` : ''}` : live ? 'Waiting for motion data…' : 'No motion data was recorded.'}</p>
    </div>
    <div class="modes" role="group" aria-label="Motion view">
      <button class:on={mode === 'orientation'} aria-pressed={mode === 'orientation'} onclick={() => (mode = 'orientation')}>Orientation</button>
      <button class:on={mode === 'path'} aria-pressed={mode === 'path'} onclick={() => (mode = 'path')}>Path <small>approx.</small></button>
    </div>
  </header>

  <div class="stage" bind:this={host} aria-hidden="true">
    {#if webglFailed}<p class="fallback">3D view is unavailable in this browser.</p>{/if}
    {#if mode === 'path'}<p class="warning">Approximate: phone sensors drift, so read this as the shape of the movement, not exact distances.</p>{/if}
    <p class="hint">Drag to look around</p>
  </div>

  <button class="strip-button" onclick={stripClick} aria-label="Motion intensity over the recording, events marked in colour. Click to jump the video there.">
    <canvas class="strip" bind:this={strip} aria-hidden="true"></canvas>
  </button>

  <div class="legend">
    <span><i class="ramp"></i>Calm → vigorous</span>
    <span><i class="dot impact"></i>Impact</span>
    <span><i class="dot shaking"></i>Shaking / sudden movement</span>
  </div>

  {#if events.length}
    <ul class="events">
      {#each events as event (event.t_ms + event.kind)}
        <li class:past={event.t_ms <= currentMs}>
          <button onclick={() => onseek?.(Math.max(0, event.t_ms - 2000))} disabled={!onseek}>
            <i class="dot {event.kind === 'impact' ? 'impact' : 'shaking'}"></i>
            <span class="time">{formatTime(event.t_ms)}</span>{event.label}
          </button>
        </li>
      {/each}
    </ul>
  {:else if recentEvents.length === 0 && samples.length}
    <p class="none">No impacts or violent movement detected.</p>
  {/if}
</section>

<style>
  .motion{display:grid;gap:.6rem}
  header{display:flex;justify-content:space-between;align-items:flex-start;gap:.8rem;flex-wrap:wrap}
  h3{margin:0;font-size:.95rem}header p{margin:.15rem 0 0;color:var(--muted);font-size:.82rem}
  .modes{display:flex;border:1px solid var(--line-strong);border-radius:8px;overflow:hidden}
  .modes button{border:0;background:var(--surface);padding:.4rem .7rem;font-weight:700;font-size:.8rem;color:var(--ink-2);cursor:pointer}
  .modes button.on{background:var(--navy);color:#fff}.modes small{font-weight:600;opacity:.75}
  .stage{position:relative;height:300px;border-radius:12px;overflow:hidden;background:#0b0f12;cursor:grab}
  .stage :global(canvas){display:block;width:100%;height:100%}
  .warning{position:absolute;left:.6rem;right:.6rem;top:.6rem;margin:0;background:#3d2c08e6;color:#ffd99a;font-size:.75rem;font-weight:600;padding:.35rem .55rem;border-radius:6px;pointer-events:none}
  .hint{position:absolute;right:.6rem;bottom:.5rem;margin:0;color:#7d8f96;font-size:.7rem;pointer-events:none}
  .fallback{position:absolute;inset:0;display:grid;place-items:center;margin:0;color:#b9c6cc}
  .strip-button{display:block;width:100%;padding:0;border:0;background:none;cursor:pointer;border-radius:8px}
  .strip{width:100%;height:44px;background:#0b0f12;border-radius:8px;display:block}
  .legend{display:flex;gap:1rem;flex-wrap:wrap;font-size:.75rem;color:var(--muted);font-weight:600}
  .legend span{display:inline-flex;align-items:center;gap:.35rem}
  .ramp{display:inline-block;width:34px;height:8px;border-radius:4px;background:linear-gradient(90deg,#184f95,#3987e5,#cde2fb)}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%}
  .dot.impact{background:#e5483f}.dot.shaking{background:#eda100}
  .events{list-style:none;margin:0;padding:0;display:grid;gap:.25rem}
  .events button{display:flex;align-items:center;gap:.5rem;width:100%;border:1px solid var(--line);background:var(--surface);border-radius:8px;padding:.45rem .6rem;text-align:left;font-size:.84rem;cursor:pointer;color:var(--ink)}
  .events li:not(.past) button{opacity:.55}
  .events .time{font-variant-numeric:tabular-nums;font-weight:800;color:var(--ink-2);min-width:2.6rem}
  .none{margin:0;color:var(--muted);font-size:.82rem}
</style>
