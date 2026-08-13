<script lang="ts">
  import { onDestroy } from 'svelte';

  let { url, token }: { url: string; token: string } = $props();
  let container: HTMLDivElement;
  let video = $state<HTMLVideoElement | null>(null);
  let watching = $state(false);
  let paused = $state(false);
  let muted = $state(true);
  let connecting = $state(false);
  let error = $state('');
  let room: import('livekit-client').Room | null = null;
  let recorder = $state.raw<MediaRecorder | null>(null);
  let replayUrl = $state('');
  let replayVideo = $state.raw<HTMLVideoElement | null>(null);
  let chunks: Blob[] = [];
  let bufferedChunks = $state(0);
  let bufferStartedAt = $state(0);

  function prepareVideo(element: HTMLMediaElement) {
    if (!(element instanceof HTMLVideoElement)) return;
    video?.remove();
    video = element;
    video.autoplay = true;
    video.playsInline = true;
    video.controls = true;
    video.muted = muted;
    video.setAttribute('controlsList', 'nodownload');
    container.appendChild(video);
    video.play().catch(() => {});
    startReplayBuffer(video.srcObject);
  }

  function startReplayBuffer(source: MediaProvider | null) {
    if (!(source instanceof MediaStream) || recorder || typeof MediaRecorder === 'undefined') return;
    const mimeType = ['video/webm;codecs=vp8,opus', 'video/webm;codecs=vp8', 'video/webm']
      .find((type) => MediaRecorder.isTypeSupported(type));
    try {
      recorder = new MediaRecorder(source, mimeType ? { mimeType } : undefined);
      chunks = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) {
          chunks.push(event.data);
          bufferedChunks = chunks.length;
        }
      };
      recorder.start(1000);
      bufferStartedAt = Date.now();
    } catch {
      recorder = null;
    }
  }

  function openReplay() {
    if (!recorder || chunks.length === 0) return;
    recorder.requestData();
    setTimeout(() => {
      if (!recorder || chunks.length === 0) return;
      if (replayUrl) URL.revokeObjectURL(replayUrl);
      replayUrl = URL.createObjectURL(new Blob(chunks, { type: recorder.mimeType || 'video/webm' }));
      video?.pause();
      paused = true;
      setTimeout(() => replayVideo?.play().catch(() => {}));
    }, 100);
  }

  function closeReplay() {
    replayVideo?.pause();
    if (replayUrl) URL.revokeObjectURL(replayUrl);
    replayUrl = '';
    goLive();
  }

  async function watch() {
    connecting = true;
    error = '';
    try {
      const livekit = await import('livekit-client');
      room = new livekit.Room({ adaptiveStream: true, dynacast: true });
      room.on(livekit.RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === livekit.Track.Kind.Video) prepareVideo(track.attach());
      });
      room.on(livekit.RoomEvent.Disconnected, () => {
        error = 'The live stream ended. Any completed recording is available below.';
      });
      await room.connect(url, token);
      watching = true;
      for (const participant of room.remoteParticipants.values()) {
        for (const publication of participant.videoTrackPublications.values()) {
          if (publication.track) prepareVideo(publication.track.attach());
        }
      }
    } catch {
      error = 'The user’s live video is currently unavailable.';
    } finally {
      connecting = false;
    }
  }

  async function togglePause() {
    if (!video) return;
    if (video.paused) {
      await video.play();
      paused = false;
    } else {
      video.pause();
      paused = true;
    }
  }

  function toggleMute() {
    if (!video) return;
    muted = !muted;
    video.muted = muted;
  }

  async function pictureInPicture() {
    if (!video || !document.pictureInPictureEnabled) return;
    if (document.pictureInPictureElement) await document.exitPictureInPicture();
    else await video.requestPictureInPicture();
  }

  async function fullscreen() {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await container.requestFullscreen();
  }

  function goLive() {
    // WebRTC is a real-time feed. Playing again discards the paused frames and
    // reconnects the viewer to the current moment in the sender's stream.
    video?.play();
    paused = false;
  }

  onDestroy(() => {
    if (recorder?.state !== 'inactive') recorder?.stop();
    if (replayUrl) URL.revokeObjectURL(replayUrl);
    video?.remove();
    room?.disconnect();
  });
</script>

{#if !watching}
  <button class="button" disabled={connecting} onclick={watch}>
    {connecting ? 'Connecting…' : 'Watch User’s Video'}
  </button>
{/if}
{#if error}<p class="error">{error}</p>{/if}
<div class="player" class:watching bind:this={container}>
  {#if watching && !video}<div class="waiting">Waiting for the user’s camera…</div>{/if}
</div>
{#if watching}
  <div class="toolbar" aria-label="Live video controls">
    <button onclick={togglePause}>{paused ? '▶ Resume' : 'Ⅱ Pause'}</button>
    {#if paused}<button class="live" onclick={goLive}>● Go Live</button>{/if}
    <button onclick={toggleMute}>{muted ? 'Unmute' : 'Mute'}</button>
    <button class="replay" disabled={!recorder || bufferedChunks===0} onclick={openReplay}>↶ Replay recording so far</button>
    <button onclick={pictureInPicture}>Picture in Picture</button>
    <button onclick={fullscreen}>Fullscreen</button>
  </div>
  <p class="hint">Replay contains the video received since this officer opened the live feed. The secure server recording continues independently.</p>
{/if}
{#if replayUrl}
  <div class="replay-panel">
    <div class="replay-head"><div><strong>Recording so far</strong><span>Buffered from {new Date(bufferStartedAt).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span></div><button onclick={closeReplay}>Close replay and return live</button></div>
    <!-- svelte-ignore a11y_media_has_caption -->
    <video bind:this={replayVideo} src={replayUrl} controls playsinline></video>
    <p>Drag the timeline to review any part received so far. Close this replay to return to the current live moment.</p>
  </div>
{/if}

<style>
  .player{display:none;position:relative;background:#071115;border-radius:10px;overflow:hidden;margin-top:.7rem;aspect-ratio:16/9}.player.watching{display:grid;place-items:center}.waiting{color:#b8c5ca;font-size:.85rem}.toolbar{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.55rem}.toolbar button,.replay-head button{border:1px solid #b8c9ce;background:#fff;color:var(--navy);border-radius:6px;padding:.45rem .65rem;font-weight:700;cursor:pointer}.toolbar button:hover,.replay-head button:hover{background:#edf4f5}.toolbar button:disabled{opacity:.45;cursor:not-allowed}.toolbar .live{color:#a82924}.toolbar .replay{background:#e7f3f5;border-color:#9cc6ce}.hint{font-size:.72rem;color:var(--muted);line-height:1.4;margin:.45rem 0 0}.replay-panel{position:fixed;z-index:200;inset:1.5rem;background:#101a1e;border-radius:12px;padding:1rem;display:grid;grid-template-rows:auto minmax(0,1fr) auto;gap:.75rem;box-shadow:0 20px 70px #0008}.replay-head{display:flex;align-items:center;justify-content:space-between;gap:1rem;color:white}.replay-head div{display:grid}.replay-head span{font-size:.72rem;color:#b9c8cd}.replay-panel video{width:100%;height:100%;min-height:0;object-fit:contain;background:#050a0c;border-radius:8px}.replay-panel p{color:#b9c8cd;font-size:.75rem;margin:0}:global(.player video){width:100%;height:100%;object-fit:contain;background:#071115}:global(.player:fullscreen video){height:100vh}@media(max-width:600px){.toolbar button{flex:1;white-space:nowrap}.hint{font-size:.68rem}.replay-panel{inset:.5rem;padding:.7rem}.replay-head{align-items:flex-start;flex-direction:column}.replay-head button{width:100%}}
</style>
