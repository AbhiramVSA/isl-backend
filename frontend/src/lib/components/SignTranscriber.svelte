<script lang="ts">
  import { onDestroy } from 'svelte';
  import { api, FriendlyError } from '$lib/api/client';
  import HolisticOverlay from '$lib/components/HolisticOverlay.svelte';

  interface Alternative { word: string; confidence: number }
  interface TranscribedWord {
    word: string; confidence: number; start_seconds: number; end_seconds: number;
    alternatives: Alternative[];
  }
  interface Transcription { transcript: string; words: TranscribedWord[]; model: string }

  let preview = $state<HTMLVideoElement | null>(null);
  let stream = $state<MediaStream | null>(null);
  let recorder = $state<MediaRecorder | null>(null);
  let recording = $state(false);
  let processing = $state(false);
  let error = $state('');
  let words = $state<TranscribedWord[]>([]);
  let stopTimer: ReturnType<typeof setTimeout> | null = null;
  const transcript = $derived(words.map((item) => item.word).join(' '));

  function supportedMimeType(): string {
    for (const type of ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm', 'video/mp4']) {
      if (MediaRecorder.isTypeSupported(type)) return type;
    }
    return '';
  }

  async function openCamera() {
    error = '';
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 960 }, height: { ideal: 720 }, facingMode: 'user' },
        audio: false
      });
      if (!preview) throw new Error("Camera preview is unavailable");
      preview.srcObject = stream;
      await preview.play();
    } catch {
      error = 'Camera access was blocked. Allow camera access and try again.';
    }
  }

  async function startRecording() {
    if (!stream) await openCamera();
    if (!stream) return;
    error = '';
    const chunks: Blob[] = [];
    const mimeType = supportedMimeType();
    recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
    recorder.onerror = () => { error = 'The browser could not record this clip.'; recording = false; };
    recorder.onstop = async () => {
      recording = false;
      const type = recorder?.mimeType.split(';')[0] || 'video/webm';
      const blob = new Blob(chunks, { type });
      await submitClip(blob, type);
    };
    recorder.start(250);
    recording = true;
    stopTimer = setTimeout(stopRecording, 8000);
  }

  function stopRecording() {
    if (stopTimer) clearTimeout(stopTimer);
    stopTimer = null;
    if (recorder?.state === 'recording') recorder.stop();
  }

  async function submitClip(blob: Blob, type: string) {
    if (!blob.size) { error = 'The recorded clip was empty.'; return; }
    processing = true;
    error = '';
    const form = new FormData();
    form.append('video', blob, type === 'video/mp4' ? 'signing.mp4' : 'signing.webm');
    try {
      const result = await api<Transcription>('/officer/transcription', { method: 'POST', body: form });
      words = result.words;
    } catch (cause) {
      error = cause instanceof FriendlyError ? cause.message : 'This clip could not be transcribed.';
    } finally {
      processing = false;
    }
  }

  function removeWord(index: number) { words = words.filter((_, wordIndex) => wordIndex !== index); }
  function closeCamera() {
    if (recording) stopRecording();
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    if (preview) preview.srcObject = null;
  }

  onDestroy(() => {
    if (stopTimer) clearTimeout(stopTimer);
    stream?.getTracks().forEach((track) => track.stop());
  });
</script>

<section class="transcriber" aria-labelledby="sign-transcriber-title">
  <div class="transcriber-head">
    <div>
      <p class="eyebrow">exp1 model</p>
      <h2 id="sign-transcriber-title">Try sign transcription</h2>
      <p>Record one clear sign at a time. The model checks each 2.5-second part of the clip.</p>
    </div>
    {#if stream}<button class="plain" onclick={closeCamera} disabled={processing}>Close camera</button>{/if}
  </div>

  <div class="transcriber-grid">
    <div class="camera" class:active={stream}>
      <video bind:this={preview} muted playsinline aria-label="Camera preview"></video>
      {#if stream && preview}<HolisticOverlay video={preview} />{/if}

      {#if !stream}<button class="button secondary" onclick={openCamera}>Open camera</button>{/if}
      {#if recording}<span class="recording-dot">Recording</span>{/if}
    </div>
    <div class="result" aria-live="polite">
      <span class="result-label">Rough transcript</span>
      {#if processing}
        <p class="working">Reading the signs. This can take up to a minute on the first run.</p>
      {:else if words.length}
        <p class="transcript">{transcript}</p>
        <div class="word-list" aria-label="Detected words">
          {#each words as item, index}
            <button title="Remove this word" onclick={() => removeWord(index)}>
              <span>{item.word}</span><small>{Math.round(item.confidence * 100)}%</small><b aria-hidden="true">×</b>
            </button>
          {/each}
        </div>
        <button class="plain" onclick={() => words = []}>Clear transcript</button>
      {:else}
        <p class="placeholder">Detected words will appear here. You can remove any wrong word.</p>
      {/if}
    </div>
  </div>

  {#if error}<div class="error" role="alert">{error}</div>{/if}
  <div class="actions">
    {#if recording}
      <button class="button danger" onclick={stopRecording}>Stop and transcribe</button>
    {:else}
      <button class="button" onclick={startRecording} disabled={processing}>Record signing clip</button>
    {/if}
    <span>Recording stops after 8 seconds.</span>
  </div>
</section>

<style>
  .transcriber{background:white;border:1px solid var(--line);border-radius:10px;padding:1.15rem;margin:0 0 2.2rem}.transcriber-head{display:flex;justify-content:space-between;gap:1rem;align-items:start;margin-bottom:1rem}.transcriber h2{margin:.1rem 0 .3rem;color:#193744;font-size:1.25rem}.transcriber p{margin:.2rem 0;color:var(--muted)}.transcriber-grid{display:grid;grid-template-columns:minmax(280px,.9fr) minmax(300px,1.1fr);gap:1rem}.camera{position:relative;aspect-ratio:4/3;min-height:250px;border-radius:9px;background:#e8edef;display:grid;place-items:center;overflow:hidden}.camera video{display:none;width:100%;height:100%;min-height:250px;object-fit:cover;transform:scaleX(-1)}.camera.active video{display:block}.recording-dot{position:absolute;top:.8rem;left:.8rem;background:#9b211d;color:white;padding:.4rem .65rem;border-radius:999px;font-size:.75rem;font-weight:800}.result{border:1px solid var(--line);border-radius:9px;padding:1rem;min-height:250px}.result-label{display:block;color:var(--muted);font-size:.76rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em}.result .transcript{font-size:1.45rem;line-height:1.4;color:#193744;margin:1rem 0}.placeholder,.working{padding:2.3rem .5rem;text-align:center}.word-list{display:flex;flex-wrap:wrap;gap:.45rem;margin:1rem 0}.word-list button{display:flex;align-items:center;gap:.4rem;border:1px solid #bdd4dc;background:#edf5f7;color:var(--navy);border-radius:999px;padding:.45rem .55rem .45rem .7rem;cursor:pointer}.word-list small{color:var(--muted)}.word-list b{font-size:1rem}.plain{border:0;background:transparent;color:var(--blue);font-weight:750;padding:.35rem;cursor:pointer}.plain:disabled{opacity:.5}.actions{display:flex;align-items:center;gap:.8rem;margin-top:1rem}.actions span{font-size:.8rem;color:var(--muted)}.error{margin-top:1rem}@media(max-width:800px){.transcriber-grid{grid-template-columns:1fr}.camera,.camera video{min-height:220px}.result{min-height:180px}.transcriber-head{align-items:flex-start}.actions{align-items:flex-start;flex-direction:column}}
</style>
