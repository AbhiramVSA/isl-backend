import { useEffect, useRef, useState } from "react";

export type WebcamStatus = "idle" | "requesting" | "live" | "error";

export interface WebcamState {
  status: WebcamStatus;
  error: string | null;
  stream: MediaStream | null;
  width: number;
  height: number;
}

/** Opens the default camera while `enabled` and releases it on disable/unmount. */
export function useWebcam(enabled: boolean): WebcamState {
  const [status, setStatus] = useState<WebcamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    if (!enabled) {
      setStatus("idle");
      return;
    }
    let cancelled = false;
    setStatus("requesting");
    setError(null);

    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus("error");
      setError("This browser does not expose getUserMedia (camera access needs https or localhost).");
      return;
    }

    navigator.mediaDevices
      .getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 }, facingMode: "user" },
        audio: false,
      })
      .then((s) => {
        if (cancelled) {
          s.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = s;
        const settings = s.getVideoTracks()[0]?.getSettings();
        setSize({ width: settings?.width ?? 0, height: settings?.height ?? 0 });
        setStream(s);
        setStatus("live");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setStatus("error");
        setError(e instanceof Error ? `${e.name}: ${e.message}` : String(e));
      });

    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      setStream(null);
      setStatus("idle");
    };
  }, [enabled]);

  return { status, error, stream, width: size.width, height: size.height };
}
