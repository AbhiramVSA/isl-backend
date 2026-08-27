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

  let { video }: { video: HTMLVideoElement } = $props();
  let canvas: HTMLCanvasElement;
  let status = $state<'loading' | 'tracking' | 'error'>('loading');
  let poseVisible = $state(false);
  let leftHandVisible = $state(false);
  let rightHandVisible = $state(false);
  let frameRequest = 0;
  let landmarker: HolisticLandmarker | null = null;
  let drawing: DrawingUtils | null = null;
  let destroyed = false;
  let lastVideoTime = -1;
  let lastDetectionTime = 0;

  function drawResult(result: HolisticLandmarkerResult) {
    const context = canvas.getContext('2d');
    if (!context || !drawing || !video.videoWidth || !video.videoHeight) return;
    if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
    }
    context.clearRect(0, 0, canvas.width, canvas.height);

    const pose = result.poseLandmarks[0];
    const leftHand = result.leftHandLandmarks[0];
    const rightHand = result.rightHandLandmarks[0];
    poseVisible = Boolean(pose);
    leftHandVisible = Boolean(leftHand);
    rightHandVisible = Boolean(rightHand);

    if (pose) {
      drawing.drawConnectors(pose, HolisticLandmarker.POSE_CONNECTIONS, {
        color: '#65f28f', lineWidth: 3
      });
      drawing.drawLandmarks(pose, { color: '#ffffff', fillColor: '#153b50', radius: 2.5 });
    }
    if (leftHand) {
      drawing.drawConnectors(leftHand, HolisticLandmarker.HAND_CONNECTIONS, {
        color: '#54d8ff', lineWidth: 4
      });
      drawing.drawLandmarks(leftHand, { color: '#ffffff', fillColor: '#08799c', radius: 3 });
    }
    if (rightHand) {
      drawing.drawConnectors(rightHand, HolisticLandmarker.HAND_CONNECTIONS, {
        color: '#ffb84d', lineWidth: 4
      });
      drawing.drawLandmarks(rightHand, { color: '#ffffff', fillColor: '#b96500', radius: 3 });
    }
  }

  function trackFrame(now: number) {
    if (destroyed || !landmarker) return;
    if (
      video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
      video.currentTime !== lastVideoTime &&
      now - lastDetectionTime >= 70
    ) {
      lastVideoTime = video.currentTime;
      lastDetectionTime = now;
      try {
        landmarker.detectForVideo(video, now, drawResult);
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
        if (destroyed) {
          loaded.close();
          return;
        }
        landmarker = loaded;
        const context = canvas.getContext('2d');
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

<canvas bind:this={canvas} class="landmarks" aria-hidden="true"></canvas>
<div class="tracking-status" aria-live="polite">
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
  .landmarks{position:absolute;inset:0;width:100%;height:100%;z-index:2;pointer-events:none;transform:scaleX(-1)}
  .tracking-status{position:absolute;z-index:3;left:.7rem;right:.7rem;bottom:.65rem;display:flex;gap:.35rem;flex-wrap:wrap;pointer-events:none}.tracking-status span{background:#17272ecc;color:#d4dee2;border:1px solid #ffffff38;border-radius:999px;padding:.3rem .5rem;font-size:.68rem;font-weight:800;backdrop-filter:blur(3px)}.tracking-status span.found{background:#176247e6;color:white;border-color:#75dbb7}.tracking-status .loading{background:#805000e6;color:white}.tracking-status .failed{background:#922b26e6;color:white}
</style>
