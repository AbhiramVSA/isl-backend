<script lang="ts">
  let { src, label, downloadName = 'incident-video' }: { src: string; label: string; downloadName?: string } = $props();
  let video: HTMLVideoElement | null = null;
  let rate = $state('1');

  function seek(seconds: number) {
    if (!video) return;
    video.currentTime = Math.max(0, Math.min(video.duration || Infinity, video.currentTime + seconds));
  }
  function changeRate() {
    if (video) video.playbackRate = Number(rate);
  }
  async function pictureInPicture() {
    if (!video || !document.pictureInPictureEnabled) return;
    if (document.pictureInPictureElement) await document.exitPictureInPicture();
    else await video.requestPictureInPicture();
  }
  async function fullscreen() {
    if (!video) return;
    if (document.fullscreenElement) await document.exitFullscreen();
    else await video.requestFullscreen();
  }
</script>

<div class="saved-player">
  <!-- svelte-ignore a11y_media_has_caption -->
  <video bind:this={video} src={src} controls playsinline preload="metadata" aria-label={label}></video>
  <div class="tools" aria-label="Recorded video controls">
    <button onclick={() => seek(-10)}>↶ 10 sec</button>
    <button onclick={() => seek(10)}>10 sec ↷</button>
    <label>Speed
      <select bind:value={rate} onchange={changeRate}>
        <option value="0.5">0.5×</option><option value="0.75">0.75×</option><option value="1">Normal</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option>
      </select>
    </label>
    <button onclick={pictureInPicture}>Picture in Picture</button>
    <button onclick={fullscreen}>Fullscreen</button>
    <a href={src} download={downloadName}>Download</a>
  </div>
</div>

<style>
  .saved-player{display:grid;gap:.5rem}.saved-player video{width:100%;max-height:520px;background:#071115;border-radius:8px}.tools{display:flex;align-items:center;flex-wrap:wrap;gap:.4rem}.tools button,.tools a,.tools select{border:1px solid #b8c9ce;background:#fff;color:var(--navy);border-radius:6px;padding:.42rem .6rem;font:inherit;font-size:.75rem;font-weight:700;text-decoration:none;cursor:pointer}.tools label{display:flex;align-items:center;gap:.35rem;font-size:.72rem;color:var(--muted);font-weight:700}.tools select{padding:.36rem}.tools button:hover,.tools a:hover{background:#edf4f5}@media(max-width:600px){.tools button,.tools a{flex:1;text-align:center}}
</style>
