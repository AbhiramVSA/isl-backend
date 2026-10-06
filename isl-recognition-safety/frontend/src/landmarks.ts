import { HolisticLandmarker, type HolisticLandmarkerResult, type NormalizedLandmark } from "@mediapipe/tasks-vision";
import type { HandArray, LandmarkFrame, LandmarksMessage, PoseArray } from "./types";

interface Connection {
  start: number;
  end: number;
}

// Standard MediaPipe topology, used only if the library does not export the lists.
const POSE_FALLBACK: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 7], [0, 4], [4, 5], [5, 6], [6, 8], [9, 10],
  [11, 12], [11, 13], [13, 15], [15, 17], [15, 19], [15, 21], [17, 19],
  [12, 14], [14, 16], [16, 18], [16, 20], [16, 22], [18, 20],
  [11, 23], [12, 24], [23, 24], [23, 25], [24, 26], [25, 27], [26, 28],
  [27, 29], [28, 30], [29, 31], [30, 32], [27, 31], [28, 32],
];
const HAND_FALLBACK: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17], [17, 18], [18, 19], [19, 20],
];

function pickConnections(lib: unknown, fallback: [number, number][]): Connection[] {
  if (Array.isArray(lib) && lib.length > 0) return lib as Connection[];
  return fallback.map(([start, end]) => ({ start, end }));
}

export const POSE_CONNECTIONS: Connection[] = pickConnections(
  (HolisticLandmarker as unknown as { POSE_CONNECTIONS?: unknown }).POSE_CONNECTIONS,
  POSE_FALLBACK,
);
export const HAND_CONNECTIONS: Connection[] = pickConnections(
  (HolisticLandmarker as unknown as { HAND_CONNECTIONS?: unknown }).HAND_CONNECTIONS,
  HAND_FALLBACK,
);

const poseToArray = (lms: NormalizedLandmark[]): PoseArray =>
  lms.map((l) => [l.x, l.y, l.z, typeof l.visibility === "number" ? l.visibility : 0]);
const handToArray = (lms: NormalizedLandmark[]): HandArray => lms.map((l) => [l.x, l.y, l.z]);

/** Convert a HolisticLandmarker result into the wire message from the API contract. */
export function toLandmarksMessage(
  r: HolisticLandmarkerResult,
  tMs: number,
  width: number,
  height: number,
): LandmarksMessage {
  const pose = r.poseLandmarks[0];
  const left = r.leftHandLandmarks[0];
  const right = r.rightHandLandmarks[0];
  return {
    type: "landmarks",
    t_ms: Math.round(tMs),
    width,
    height,
    pose: pose && pose.length === 33 ? poseToArray(pose) : null,
    left_hand: left && left.length === 21 ? handToArray(left) : null,
    right_hand: right && right.length === 21 ? handToArray(right) : null,
    face: Array.isArray(r.faceLandmarks) && r.faceLandmarks.length > 0,
  };
}

export interface OverlayColors {
  pose: string;
  left: string;
  right: string;
  joint: string;
}

export const OVERLAY_COLORS: OverlayColors = {
  pose: "rgba(90, 176, 255, 0.85)",
  left: "rgba(255, 168, 76, 0.95)",
  right: "rgba(122, 222, 170, 0.95)",
  joint: "rgba(236, 242, 250, 0.9)",
};

type Pt = readonly number[];

function drawSet(
  ctx: CanvasRenderingContext2D,
  pts: readonly Pt[],
  conns: Connection[],
  w: number,
  h: number,
  stroke: string,
  lineWidth: number,
  minVisibility: number,
): void {
  ctx.lineWidth = lineWidth;
  ctx.strokeStyle = stroke;
  ctx.beginPath();
  for (const c of conns) {
    const a = pts[c.start];
    const b = pts[c.end];
    if (!a || !b) continue;
    if ((a[3] ?? 1) < minVisibility || (b[3] ?? 1) < minVisibility) continue;
    ctx.moveTo(a[0]! * w, a[1]! * h);
    ctx.lineTo(b[0]! * w, b[1]! * h);
  }
  ctx.stroke();
  ctx.fillStyle = OVERLAY_COLORS.joint;
  for (const p of pts) {
    if ((p[3] ?? 1) < minVisibility) continue;
    ctx.beginPath();
    ctx.arc(p[0]! * w, p[1]! * h, lineWidth * 0.9, 0, Math.PI * 2);
    ctx.fill();
  }
}

/** Draw pose + hand skeletons. Coordinates are normalised (0..1) image coordinates. */
export function drawSkeleton(
  ctx: CanvasRenderingContext2D,
  frame: Pick<LandmarkFrame, "pose" | "left_hand" | "right_hand">,
  w: number,
  h: number,
): void {
  ctx.clearRect(0, 0, w, h);
  const lw = Math.max(1.5, Math.min(w, h) / 240);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  if (frame.pose) drawSet(ctx, frame.pose, POSE_CONNECTIONS, w, h, OVERLAY_COLORS.pose, lw, 0.4);
  if (frame.left_hand) drawSet(ctx, frame.left_hand, HAND_CONNECTIONS, w, h, OVERLAY_COLORS.left, lw * 0.8, 0);
  if (frame.right_hand) drawSet(ctx, frame.right_hand, HAND_CONNECTIONS, w, h, OVERLAY_COLORS.right, lw * 0.8, 0);
}
