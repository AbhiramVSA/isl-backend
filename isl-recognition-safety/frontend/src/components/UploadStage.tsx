import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchJob, submitVideo } from "../api";
import { clock, nearestByTime } from "../format";
import { drawSkeleton } from "../landmarks";
import type { AnalyzeResult, Update } from "../types";
import { Badge, Empty } from "./ui";

const POLL_MS = 700;

type Phase =
  | { kind: "idle" }
  | { kind: "uploading"; name: string }
  | { kind: "polling"; jobId: string; state: string; progress: number }
  | { kind: "done"; result: AnalyzeResult }
  | { kind: "error"; message: string };

const SEV_CLASS: Record<string, string> = { WATCH: "tone-info", WARNING: "tone-warn", CRITICAL: "tone-crit" };

export function UploadStage({ onSnapshot }: { onSnapshot: (u: Update | null) => void }) {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [file, setFile] = useState<File | null>(null);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const lastIndexRef = useRef(-2);

  const result = phase.kind === "done" ? phase.result : null;

  // Object URL lifecycle.
  useEffect(() => {
    if (!file) {
      setObjectUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // Poll the job.
  useEffect(() => {
    if (phase.kind !== "polling") return;
    const jobId = phase.jobId;
    let cancelled = false;
    let timer = 0;
    const poll = async () => {
      try {
        const job = await fetchJob(jobId);
        if (cancelled) return;
        if (job.state === "done" && job.result) {
          setPhase({ kind: "done", result: job.result });
          return;
        }
        if (job.state === "error") {
          setPhase({ kind: "error", message: job.error ?? "analysis failed without a message" });
          return;
        }
        setPhase({ kind: "polling", jobId, state: job.state, progress: job.progress });
      } catch (e) {
        if (cancelled) return;
        setPhase({ kind: "error", message: e instanceof Error ? e.message : String(e) });
        return;
      }
      timer = window.setTimeout(poll, POLL_MS);
    };
    timer = window.setTimeout(poll, POLL_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [phase.kind === "polling" ? phase.jobId : null]); // eslint-disable-line react-hooks/exhaustive-deps

  const pushSnapshot = useCallback(
    (tSec: number) => {
      if (!result) return;
      const tMs = tSec * 1000;
      const idx = nearestByTime(result.timeline, tMs);
      if (idx !== lastIndexRef.current) {
        lastIndexRef.current = idx;
        onSnapshot(idx >= 0 ? (result.timeline[idx] ?? null) : null);
      }
      const canvas = canvasRef.current;
      const video = videoRef.current;
      if (canvas && video) {
        const vw = video.videoWidth || result.width;
        const vh = video.videoHeight || result.height;
        if (canvas.width !== vw || canvas.height !== vh) {
          canvas.width = vw;
          canvas.height = vh;
        }
        const ctx = canvas.getContext("2d");
        if (ctx) {
          const frames = result.landmark_frames;
          if (frames && frames.length > 0) {
            const fi = nearestByTime(frames, tMs);
            const f = frames[fi];
            if (f) drawSkeleton(ctx, f, vw, vh);
          } else {
            ctx.clearRect(0, 0, vw, vh);
          }
        }
      }
    },
    [result, onSnapshot],
  );

  // Drive snapshots from playback time (rAF while playing, plus seek/timeupdate).
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !result) return;
    lastIndexRef.current = -2;
    let raf = 0;
    let running = false;
    const frame = () => {
      if (!running) return;
      setTime(v.currentTime);
      pushSnapshot(v.currentTime);
      raf = requestAnimationFrame(frame);
    };
    const onPlay = () => {
      running = true;
      raf = requestAnimationFrame(frame);
    };
    const onPause = () => {
      running = false;
      cancelAnimationFrame(raf);
      setTime(v.currentTime);
      pushSnapshot(v.currentTime);
    };
    const onSeek = () => {
      setTime(v.currentTime);
      pushSnapshot(v.currentTime);
    };
    const onMeta = () => setDuration(v.duration || result.duration_s);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    v.addEventListener("ended", onPause);
    v.addEventListener("seeked", onSeek);
    v.addEventListener("loadedmetadata", onMeta);
    if (v.readyState >= 1) onMeta();
    pushSnapshot(v.currentTime);
    return () => {
      running = false;
      cancelAnimationFrame(raf);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
      v.removeEventListener("ended", onPause);
      v.removeEventListener("seeked", onSeek);
      v.removeEventListener("loadedmetadata", onMeta);
    };
  }, [result, pushSnapshot]);

  // Clear the parent's snapshot when leaving a result.
  useEffect(() => {
    if (!result) onSnapshot(null);
  }, [result, onSnapshot]);

  const start = async (f: File) => {
    setFile(f);
    setPhase({ kind: "uploading", name: f.name });
    try {
      const jobId = await submitVideo(f);
      setPhase({ kind: "polling", jobId, state: "queued", progress: 0 });
    } catch (e) {
      setPhase({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    }
  };

  const scrub = (t: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = t;
    setTime(t);
  };

  const total = duration || result?.duration_s || 0;

  const markers = useMemo(() => {
    if (!result || total <= 0) return null;
    return {
      glosses: result.glosses.map((g) => ({
        id: g.id,
        left: (g.t_start_ms / 1000 / total) * 100,
        width: Math.max(0.4, ((g.t_end_ms - g.t_start_ms) / 1000 / total) * 100),
        status: g.status,
        title: `${g.display} ${Math.round(g.p * 100)}%`,
      })),
      events: result.safety_events.map((e) => ({
        id: e.id,
        left: (e.t_ms / 1000 / total) * 100,
        cls: SEV_CLASS[e.severity] ?? "tone-muted",
        title: `${e.severity}: ${e.title}`,
      })),
    };
  }, [result, total]);

  return (
    <div className="stage">
      <div className="stage-video">
        {objectUrl ? <video ref={videoRef} src={objectUrl} controls={false} playsInline preload="auto" /> : null}
        <canvas ref={canvasRef} className="overlay" />
        {!result ? (
          <div className="stage-cover stage-cover-upload">
            {phase.kind === "idle" ? (
              <>
                <span>Choose a video to analyse on the server.</span>
                <button type="button" className="btn" onClick={() => inputRef.current?.click()}>
                  Choose video
                </button>
              </>
            ) : phase.kind === "uploading" ? (
              <span>Uploading {phase.name}…</span>
            ) : phase.kind === "polling" ? (
              <>
                <span>
                  {phase.state === "queued" ? "Queued on the server" : "Analysing"} {Math.round(phase.progress * 100)}%
                </span>
                <div className="meter meter-wide">
                  <div className="meter-fill" style={{ width: `${Math.round(phase.progress * 100)}%` }} />
                </div>
              </>
            ) : phase.kind === "error" ? (
              <>
                <span className="err">{phase.message}</span>
                <button type="button" className="btn" onClick={() => inputRef.current?.click()}>
                  Choose another video
                </button>
              </>
            ) : null}
          </div>
        ) : null}
        <input
          ref={inputRef}
          type="file"
          accept="video/*"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void start(f);
            e.target.value = "";
          }}
        />
      </div>
      {result ? (
        <div className="scrub">
          <div className="scrub-row">
            <button
              type="button"
              className="btn btn-small"
              onClick={() => {
                const v = videoRef.current;
                if (!v) return;
                if (v.paused) void v.play();
                else v.pause();
              }}
            >
              Play / pause
            </button>
            <span className="scrub-time">
              {clock(time * 1000)} / {clock(total * 1000)}
            </span>
            <Badge tone="muted" title="Server-side extraction: landmarks were computed on the server">
              {result.frames} frames, {result.fps.toFixed(1)} fps, {result.width}×{result.height}
            </Badge>
            {result.landmark_frames && result.landmark_frames.length > 0 ? (
              <Badge tone="good">{result.landmark_frames.length} landmark frames</Badge>
            ) : (
              <Badge tone="muted">no landmark frames returned</Badge>
            )}
            <button type="button" className="btn btn-small btn-quiet" onClick={() => inputRef.current?.click()}>
              Another video
            </button>
          </div>
          <input
            className="scrub-range"
            type="range"
            min={0}
            max={total || 0}
            step={0.02}
            value={Math.min(time, total || 0)}
            onChange={(e) => scrub(Number(e.target.value))}
            aria-label="Timeline"
          />
          {markers ? (
            <div className="marks" aria-hidden>
              {markers.glosses.map((g) => (
                <span key={`g${g.id}`} className={`mark-gloss chip-${g.status}`} style={{ left: `${g.left}%`, width: `${g.width}%` }} title={g.title} />
              ))}
              {markers.events.map((e) => (
                <span key={`e${e.id}`} className={`mark-event ${e.cls}`} style={{ left: `${e.left}%` }} title={e.title} />
              ))}
            </div>
          ) : null}
          {result.timeline.length === 0 ? <Empty>The server returned an empty timeline for this video.</Empty> : null}
        </div>
      ) : null}
    </div>
  );
}
