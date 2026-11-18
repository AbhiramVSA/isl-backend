import { useEffect, useRef, useState } from "react";
import { FilesetResolver, HolisticLandmarker } from "@mediapipe/tasks-vision";

export type LandmarkerStatus = "idle" | "loading" | "ready" | "error";

export interface LandmarkerState {
  status: LandmarkerStatus;
  delegate: "GPU" | "CPU" | null;
  error: string | null;
  /** Stable ref; read `.current` inside the frame loop. */
  ref: React.MutableRefObject<HolisticLandmarker | null>;
}

const WASM_PATH = "/mediapipe-wasm";
const MODEL_PATH = "/models/holistic_landmarker.task";

async function create(delegate: "GPU" | "CPU"): Promise<HolisticLandmarker> {
  const fileset = await FilesetResolver.forVisionTasks(WASM_PATH);
  return HolisticLandmarker.createFromOptions(fileset, {
    baseOptions: { modelAssetPath: MODEL_PATH, delegate },
    runningMode: "VIDEO",
    outputFaceBlendshapes: false,
    outputPoseSegmentationMasks: false,
  });
}

/**
 * Loads the in-browser HolisticLandmarker when `enabled`. Tries the GPU delegate first
 * and falls back to CPU if GPU initialisation throws.
 */
export function useLandmarker(enabled: boolean): LandmarkerState {
  const ref = useRef<HolisticLandmarker | null>(null);
  const [status, setStatus] = useState<LandmarkerStatus>("idle");
  const [delegate, setDelegate] = useState<"GPU" | "CPU" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) {
      setStatus("idle");
      return;
    }
    let cancelled = false;
    setStatus("loading");
    setError(null);

    (async () => {
      let lm: HolisticLandmarker | null = null;
      let used: "GPU" | "CPU" = "GPU";
      let firstError: string | null = null;
      try {
        lm = await create("GPU");
      } catch (e) {
        firstError = e instanceof Error ? e.message : String(e);
        try {
          used = "CPU";
          lm = await create("CPU");
        } catch (e2) {
          const second = e2 instanceof Error ? e2.message : String(e2);
          if (!cancelled) {
            setStatus("error");
            setError(`GPU: ${firstError}; CPU: ${second}`);
          }
          return;
        }
      }
      if (cancelled) {
        lm.close();
        return;
      }
      ref.current = lm;
      setDelegate(used);
      setStatus("ready");
    })();

    return () => {
      cancelled = true;
      const lm = ref.current;
      ref.current = null;
      if (lm) {
        try {
          lm.close();
        } catch {
          /* already closed */
        }
      }
      setDelegate(null);
    };
  }, [enabled]);

  return { status, delegate, error, ref };
}
