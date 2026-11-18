<script lang="ts">
  import { onDestroy } from 'svelte';
  import HolisticOverlay from './HolisticOverlay.svelte';
  import PlayerControls from './PlayerControls.svelte';

  /** A recorded signing video with YouTube-style controls and an optional landmark overlay. */
  let {
    src,
    label,
    downloadName = 'signing-video',
    ontime
  }: {
    src: string;
    label: string;
    downloadName?: string;
    /** Playhead in ms, reported every animation frame while playing (for the motion view). */
    ontime?: (ms: number, durationMs: number) => void;
  } = $props();

  /** Jump to a moment (ms); used by the motion timeline. */
  export function seekTo(ms: number) { seek(ms / 1000); }

  let timeRaf = 0;
  function reportTime() {
    if (video) ontime?.(video.currentTime * 1000, (video.duration || 0) * 1000);
    if (playing) timeRaf = requestAnimationFrame(reportTime);
  }
  onDestroy(() => cancelAnimationFrame(timeRaf));

  let shell = $state<HTMLDivElement | null>(null);
  let video = $state<HTMLVideoElement | null>(null);
  let playing = $state(false);
  let current = $state(0);
  let duration = $state(0);
  let buffered = $state(0);
  let rate = $state(1);
  let overlay = $state(false);
  let aspect = $state(16 / 9);
  let rotation = $state(0);
  const sideways = $derived(rotation % 180 !== 0);
  // The stage takes the rotated shape; the video and its overlay turn together inside it.
  const stageAspect = $derived(sideways ? 1 / aspect : aspect);
  let idle = $state(false);
  let idleTimer: ReturnType<typeof setTimeout> | undefined;

  function toggle() { if (!video) return; if (video.paused) video.play(); else video.pause(); }
  function seek(seconds: number) { if (video) video.currentTime = Math.min(Math.max(0, seconds), duration || 0); }
  function setRate(value: number) { rate = value; if (video) video.playbackRate = value; }
  async function fullscreen() {
    if (!shell) return;
    if (document.fullscreenElement) await document.exitFullscreen(); else await shell.requestFullscreen();
  }
  function download() {
    const link = Object.assign(document.createElement('a'), { href: src, download: `${downloadName}.mp4` });
    document.body.append(link); link.click(); link.remove();
  }
  function wake() { idle = false; clearTimeout(idleTimer); idleTimer = setTimeout(() => { if (playing) idle = true; }, 2500); }

  function keydown(event: KeyboardEvent) {
    if ((event.target as HTMLElement).closest('[role="slider"], .menu')) return;
    const key = event.key.toLowerCase();
    if (key === ' ' || key === 'k') toggle();
    else if (key === 'j') seek(current - 10);
    else if (key === 'l') seek(current + 10);
    else if (key === 'arrowleft') seek(current - 5);
    else if (key === 'arrowright') seek(current + 5);
    else if (key === 'f') fullscreen();
    else if (key === 'o') overlay = !overlay;
    else if (key === 'r') rotation = (rotation + 90) % 360;
    // Frame-step while paused, for reading a handshape closely.
    else if (key === ',' && video?.paused) seek(current - 1 / 15);
    else if (key === '.' && video?.paused) seek(current + 1 / 15);
    else return;
    event.preventDefault(); wake();
  }
</script>

<!-- Keyboard shortcuts (k, j, l, f, o) live on the focusable player region, like YouTube. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div class="player" class:idle bind:this={shell} tabindex="0" role="region" aria-label={`${label} player`} onkeydown={keydown} onpointermove={wake}>
  <div class="stage" style:aspect-ratio={stageAspect} style:width={`min(100%, calc(var(--player-h) * ${stageAspect}))`}>
    <div class="rotor" style:width={sideways ? `${stageAspect > 0 ? (1 / stageAspect) * 100 : 100}%` : '100%'} style:height={sideways ? `${stageAspect * 100}%` : '100%'} style:transform={`translate(-50%, -50%) rotate(${rotation}deg)`}>
    <!-- Signing videos carry no audio; the transcript beside the player is the text alternative. -->
    <!-- svelte-ignore a11y_media_has_caption -->
    <video
      bind:this={video}
      {src}
      playsinline
      preload="metadata"
      onclick={toggle}
      onplay={() => { playing = true; wake(); timeRaf = requestAnimationFrame(reportTime); }}
      onpause={() => { playing = false; idle = false; }}
      ontimeupdate={() => { current = video?.currentTime ?? 0; if (!playing) reportTime(); }}
      onloadedmetadata={() => { if (!video) return; duration = video.duration; if (video.videoWidth) aspect = video.videoWidth / video.videoHeight; video.playbackRate = rate; }}
      onprogress={() => { if (video?.buffered.length) buffered = video.buffered.end(video.buffered.length - 1); }}
      onended={() => { playing = false; idle = false; }}
    ></video>
    {#if overlay && video}<HolisticOverlay {video} mirror={false} compact />{/if}
    </div>
    {#if !playing}<button class="big-play" aria-label="Play" onclick={toggle}><svg viewBox="0 0 24 24" width="34" height="34" fill="currentColor" aria-hidden="true"><path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5z"/></svg></button>{/if}
  </div>
  <PlayerControls {playing} {current} {duration} {buffered} {rate} {overlay} canDownload
    onplay={toggle} onseek={seek} onrate={setRate} onoverlay={() => (overlay = !overlay)} onfullscreen={fullscreen} ondownload={download} onrotate={() => (rotation = (rotation + 90) % 360)} />
</div>

<style>
  .player{--player-h:min(72vh,640px);position:relative;background:#0b0f12;border-radius:12px;overflow:hidden;display:flex;justify-content:center;outline:none}
  .player:focus-visible{box-shadow:0 0 0 3px #7fd0e6}
  .player:fullscreen{--player-h:100vh;border-radius:0;align-items:center}
  .stage{position:relative}
  .rotor{position:absolute;left:50%;top:50%}
  video{display:block;width:100%;height:100%;object-fit:contain;background:#000;cursor:pointer}
  .big-play{position:absolute;z-index:4;left:50%;top:50%;transform:translate(-50%,-50%);width:68px;height:68px;border-radius:50%;border:0;background:#000000a6;color:#fff;display:grid;place-items:center;cursor:pointer;padding-left:4px}
  .big-play:hover{background:#e5483f}
  .player.idle :global(.controls){opacity:0;transition:opacity .3s}
  .player.idle{cursor:none}
</style>
