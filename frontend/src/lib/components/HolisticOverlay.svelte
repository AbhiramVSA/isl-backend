<script lang="ts">
  import { onMount } from 'svelte';
  import {
    DrawingUtils,
    HolisticLandmarker,
    type HolisticLandmarkerResult
  } from '@mediapipe/tasks-vision';
  import wasmLoaderPath from '@mediapipe/tasks-vision/vision_wasm_internal.js?url';
  import wasmBinaryPath from '@mediapipe/tasks-vision/vision_wasm_internal.wasm?url';
  import { base } from '$lib/api/client';
  import { auth } from '$lib/auth.svelte';

  /**
   * MediaPipe Holistic landmarks drawn over a video or canvas, in the browser.
   *
   * `video` — a <video> (camera preview or recording); new frames are detected
   * from its currentTime. `canvas` — a canvas another component paints frames
   * into; bump `frame` whenever a new picture lands. `mirror` flips the drawing
   * for selfie previews that are shown mirrored.
   */
  let {
    video,
    canvas: sourceCanvas,
    frame = 0,
    mirror = true,
    compact = false
  }: {
    video?: HTMLVideoElement;
    canvas?: HTMLCanvasElement;
    frame?: number;
    mirror?: boolean;
    compact?: boolean;
  } = $props();

  let overlay: HTMLCanvasElement;
  let status = $state<'loading' | 'tracking' | 'error'>('loading');
  let poseVisible = $state(false);
  let leftHandVisible = $state(false);
  let rightHandVisible = $state(false);
  let frameRequest = 0;
  let landmarker: HolisticLandmarker | null = null;
  let drawing: DrawingUtils | null = null;
  let destroyed = false;
  let lastKey: number | null = null;
  let lastDetectionTime = 0;
  let lastTimestamp = 0;

  function sourceSize(): [number, number] {
    if (video) return [video.videoWidth, video.videoHeight];
    if (sourceCanvas) return [sourceCanvas.width, sourceCanvas.height];
    return [0, 0];
  }

  function drawResult(result: HolisticLandmarkerResult) {
    const context = overlay.getContext('2d');
    const [width, height] = sourceSize();
    if (!context || !drawing || !width || !height) return;
    if (overlay.width !== width || overlay.height !== height) {
      overlay.width = width;
      overlay.height = height;
    }
    context.clearRect(0, 0, overlay.width, overlay.height);

    const pose = result.poseLandmarks[0];
    const leftHand = result.leftHandLandmarks[0];
    const rightHand = result.rightHandLandmarks[0];
    poseVisible = Boolean(pose);
    leftHandVisible = Boolean(leftHand);
    rightHandVisible = Boolean(rightHand);
    const scale = Math.max(1, width / 640);

    if (pose) {
      drawing.drawConnectors(pose, HolisticLandmarker.POSE_CONNECTIONS, { color: '#65f28f', lineWidth: 3 * scale });
      drawing.drawLandmarks(pose, { color: '#ffffff', fillColor: '#153b50', radius: 2.5 * scale });
    }
    if (leftHand) {
      drawing.drawConnectors(leftHand, HolisticLandmarker.HAND_CONNECTIONS, { color: '#54d8ff', lineWidth: 4 * scale });
      drawing.drawLandmarks(leftHand, { color: '#ffffff', fillColor: '#08799c', radius: 3 * scale });
    }
    if (rightHand) {
      drawing.drawConnectors(rightHand, HolisticLandmarker.HAND_CONNECTIONS, { color: '#ffb84d', lineWidth: 4 * scale });
      drawing.drawLandmarks(rightHand, { color: '#ffffff', fillColor: '#b96500', radius: 3 * scale });
    }
  }

  function currentKey(): number | null {
    if (video) return video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA ? video.currentTime : null;
    if (sourceCanvas) return sourceCanvas.width ? frame : null;
    return null;
  }

  function trackFrame(now: number) {
    if (destroyed || !landmarker) return;
    const key = currentKey();
    if (key !== null && key !== lastKey && now - lastDetectionTime >= 70) {
      lastKey = key;
      lastDetectionTime = now;
      // MediaPipe requires strictly increasing timestamps.
      lastTimestamp = Math.max(now, lastTimestamp + 1);
      try {
        const source = (video ?? sourceCanvas)!;
        landmarker.detectForVideo(source, lastTimestamp, drawResult);
      } catch {
        status = 'error';
        return;
      }
    }
    frameRequest = requestAnimationFrame(trackFrame);
  }

  onMount(() => {
    void (async () => {
      try {
        const response = await fetch(`${base}/officer/transcription/model`, {
          headers: auth.accessToken ? { Authorization: `Bearer ${auth.accessToken}` } : {}
        });
        if (!response.ok) throw new Error('Holistic model download failed');
        const modelAssetBuffer = new Uint8Array(await response.arrayBuffer());
        const loaded = await HolisticLandmarker.createFromOptions(
          { wasmLoaderPath, wasmBinaryPath },
          {
            baseOptions: { modelAssetBuffer, delegate: 'CPU' },
            runningMode: 'VIDEO',
            minPoseDetectionConfidence: 0.5,
            minPosePresenceConfidence: 0.5,
            minHandLandmarksConfidence: 0.5,
            outputFaceBlendshapes: false,
            outputPoseSegmentationMasks: false
          }
        );
        if (destroyed) { loaded.close(); return; }
        landmarker = loaded;
        const context = overlay.getContext('2d');
        if (!context) throw new Error('Canvas is unavailable');
        drawing = new DrawingUtils(context);
        status = 'tracking';
        frameRequest = requestAnimationFrame(trackFrame);
      } catch {
        status = 'error';
      }
    })();

    return () => {
      destroyed = true;
      cancelAnimationFrame(frameRequest);
      landmarker?.close();
      landmarker = null;
    };
  });
</script>

<canvas bind:this={overlay} class="landmarks" class:mirror aria-hidden="true"></canvas>
<div class="tracking-status" class:compact aria-live="polite">
  {#if status === 'loading'}
    <span class="loading">Loading landmarks…</span>
  {:else if status === 'error'}
    <span class="failed">Landmark overlay unavailable</span>
  {:else}
    <span class:found={poseVisible}>Pose</span>
    <span class:found={leftHandVisible}>Left hand</span>
    <span class:found={rightHandVisible}>Right hand</span>
  {/if}
</div>

<style>
  .landmarks{position:absolute;inset:0;width:100%;height:100%;z-index:2;pointer-events:none}
  .landmarks.mirror{transform:scaleX(-1)}
  .tracking-status{position:absolute;z-index:3;left:.7rem;right:.7rem;bottom:.65rem;display:flex;gap:.35rem;flex-wrap:wrap;pointer-events:none}
  .tracking-status.compact{top:.65rem;bottom:auto}
  .tracking-status span{background:#17272ecc;color:#d4dee2;border:1px solid #ffffff38;border-radius:999px;padding:.3rem .5rem;font-size:.68rem;font-weight:800;backdrop-filter:blur(3px)}
  .tracking-status span.found{background:#176247e6;color:white;border-color:#75dbb7}
  .tracking-status .loading{background:#805000e6;color:white}
  .tracking-status .failed{background:#922b26e6;color:white}
</style>
