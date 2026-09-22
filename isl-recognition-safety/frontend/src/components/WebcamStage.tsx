import { useEffect, useRef, useState } from "react";
import type { HolisticLandmarker } from "@mediapipe/tasks-vision";
import { useLandmarker } from "../hooks/useLandmarker";
import { useWebcam } from "../hooks/useWebcam";
import { drawSkeleton, toLandmarksMessage } from "../landmarks";
import type { ClientMessage } from "../types";
import { Badge } from "./ui";

const LANDMARK_SEND_INTERVAL_MS = 1000 / 30;
const FRAME_SEND_INTERVAL_MS = 1000 / 15;
const FRAME_MAX_WIDTH = 640;
const JPEG_QUALITY = 0.7;

type VideoWithRvfc = HTMLVideoElement & {
  requestVideoFrameCallback?: (cb: (now: number, meta: unknown) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

export type ExtractionMode = "browser" | "server" | "waiting";

export function WebcamStage({
  enabled,
  serverSide,
  mirror,
  wsOpen,
  send,
}: {
  enabled: boolean;
  serverSide: boolean;
  mirror: boolean;
  wsOpen: boolean;
  send: (msg: ClientMessage) => boolean;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const offscreenRef = useRef<HTMLCanvasElement | null>(null);
  const sendRef = useRef(send);
  const serverSideRef = useRef(serverSide);
  sendRef.current = send;
  serverSideRef.current = serverSide;

  const webcam = useWebcam(enabled);
  const landmarker = useLandmarker(enabled && !serverSide);
  const landmarkerRef = landmarker.ref;
  const landmarkerStatus = landmarker.status;
  const statusRef = useRef(landmarkerStatus);
  statusRef.current = landmarkerStatus;

  const [detectMs, setDetectMs] = useState<number | null>(null);
  const [sentPerSec, setSentPerSec] = useState(0);

  // Attach the stream to the video element.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    v.srcObject = webcam.stream;
    if (webcam.stream) void v.play().catch(() => undefined);
    return () => {
      v.srcObject = null;
    };
  }, [webcam.stream]);

  // Per-frame loop: detect in browser (send landmarks) or capture JPEG (send frame).
  useEffect(() => {
    const video = videoRef.current as VideoWithRvfc | null;
    const canvas = canvasRef.current;
    if (!video || !canvas || !webcam.stream) return;
    let stopped = false;
    let rvfcHandle = 0;
    let rafHandle = 0;
    let lastLandmarkSend = 0;
    let lastFrameSend = 0;
    let lastTs = -1;
    let sentCount = 0;
    let sentWindowStart = performance.now();
    let detectAccum = 0;
    let detectN = 0;

    const useRvfc = typeof video.requestVideoFrameCallback === "function";

    const schedule = () => {
      if (stopped) return;
      if (useRvfc) rvfcHandle = video.requestVideoFrameCallback!(tick);
      else rafHandle = requestAnimationFrame(tick);
    };

    const tick = () => {
      if (stopped) return;
      const vw = video.videoWidth;
      const vh = video.videoHeight;
      if (video.readyState < 2 || vw === 0 || vh === 0) {
        schedule();
        return;
      }
      if (canvas.width !== vw || canvas.height !== vh) {
        canvas.width = vw;
        canvas.height = vh;
      }
      const ctx = canvas.getContext("2d");
      const now = performance.now();
      const lm: HolisticLandmarker | null = serverSideRef.current ? null : landmarkerRef.current;

      if (lm) {
        const ts = Math.max(now, lastTs + 1);
        lastTs = ts;
        const t0 = performance.now();
        let result: ReturnType<HolisticLandmarker["detectForVideo"]> | null = null;
        try {
          result = lm.detectForVideo(video, ts);
        } catch {
          result = null;
        }
        detectAccum += performance.now() - t0;
        detectN += 1;
        if (result && ctx) {
          const msg = toLandmarksMessage(result, ts, vw, vh);
          drawSkeleton(ctx, msg, vw, vh);
          if (now - lastLandmarkSend >= LANDMARK_SEND_INTERVAL_MS) {
            lastLandmarkSend = now;
            if (sendRef.current(msg)) sentCount += 1;
          }
        }
      } else if (serverSideRef.current || statusRef.current === "error") {
        if (ctx) ctx.clearRect(0, 0, vw, vh);
        if (now - lastFrameSend >= FRAME_SEND_INTERVAL_MS) {
          lastFrameSend = now;
          const scale = Math.min(1, FRAME_MAX_WIDTH / vw);
          const w = Math.round(vw * scale);
          const h = Math.round(vh * scale);
          let off = offscreenRef.current;
          if (!off) {
            off = document.createElement("canvas");
            offscreenRef.current = off;
          }
          if (off.width !== w || off.height !== h) {
            off.width = w;
            off.height = h;
          }
          const octx = off.getContext("2d");
          if (octx) {
            octx.drawImage(video, 0, 0, w, h);
            const dataUrl = off.toDataURL("image/jpeg", JPEG_QUALITY);
            const comma = dataUrl.indexOf(",");
            const jpeg = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
            if (sendRef.current({ type: "frame", t_ms: Math.round(now), jpeg })) sentCount += 1;
          }
        }
      } else if (ctx) {
        ctx.clearRect(0, 0, vw, vh);
      }

      if (now - sentWindowStart >= 1000) {
        setSentPerSec(sentCount);
        setDetectMs(detectN > 0 ? detectAccum / detectN : null);
        sentCount = 0;
        detectAccum = 0;
        detectN = 0;
        sentWindowStart = now;
      }
      schedule();
    };

    schedule();
    return () => {
      stopped = true;
      if (useRvfc && video.cancelVideoFrameCallback) video.cancelVideoFrameCallback(rvfcHandle);
      cancelAnimationFrame(rafHandle);
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    };
  }, [webcam.stream, landmarkerRef]);

  const mode: ExtractionMode = serverSide
    ? "server"
    : landmarkerStatus === "ready"
      ? "browser"
      : landmarkerStatus === "error"
        ? "server"
        : "waiting";

  return (
    <div className="stage">
      <div className={`stage-video${mirror ? " mirrored" : ""}`}>
        <video ref={videoRef} muted playsInline autoPlay />
        <canvas ref={canvasRef} className="overlay" />
        {!enabled || webcam.status !== "live" ? (
          <div className="stage-cover">
            {webcam.status === "requesting" ? (
              <span>Waiting for camera permission…</span>
            ) : webcam.status === "error" ? (
              <span className="err">Camera unavailable. {webcam.error}</span>
            ) : (
              <span>Camera is off.</span>
            )}
          </div>
        ) : null}
      </div>
      <div className="stage-bar">
        {!enabled ? (
          <span className="stage-note">Start the camera to stream landmarks to the server.</span>
        ) : mode === "browser" ? (
          <Badge tone="good" title="Landmarks are extracted in this tab; raw video never leaves the browser">
            browser landmarks ({landmarker.delegate ?? "?"})
          </Badge>
        ) : mode === "server" ? (
          <Badge
            tone="warn"
            title={
              landmarker.error
                ? `In-browser landmarker failed: ${landmarker.error}`
                : "JPEG frames are sent to the local server, which runs the landmarker"
            }
          >
            server-side landmarks
          </Badge>
        ) : (
          <Badge tone="muted">loading landmarker…</Badge>
        )}
        {landmarkerStatus === "error" && !serverSide ? (
          <span className="stage-note err" title={landmarker.error ?? ""}>
            in-browser landmarker failed, using server fallback
          </span>
        ) : null}
        {enabled && webcam.status === "live" ? (
          <span className="stage-note">
            {webcam.width > 0 ? `${webcam.width}×${webcam.height}, ` : ""}
            {detectMs != null ? `detect ${detectMs.toFixed(0)} ms, ` : ""}
            {`${sentPerSec} msg/s`}
            {wsOpen ? "" : ", not connected so frames are dropped"}
          </span>
        ) : null}
      </div>
    </div>
  );
}
