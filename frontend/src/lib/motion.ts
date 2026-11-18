/**
 * Phone-motion maths for the 3D view. Samples come from the Equal app:
 * `q` rotation-vector quaternion (device → world, Android axes: x east, y north,
 * z up), `a` gravity-free acceleration in the device frame (m/s²), `g` gyroscope
 * rate (rad/s). three.js is y-up, so world vectors map (x, y, z) → (x, z, -y).
 */
export interface MotionSample { t_ms: number; q: number[]; a: number[]; g: number[] }
export interface MotionEvent { t_ms: number; kind: 'impact' | 'jolt' | 'shaking'; label: string; value: number }
export interface MotionTrack { duration_ms: number; samples: MotionSample[]; events: MotionEvent[] }

type Vec = [number, number, number];
type Quat = [number, number, number, number];

export const magnitude = (v: number[]) => Math.hypot(v[0], v[1], v[2]);

/** Rotate a device-frame vector into the world frame with quaternion (x, y, z, w). */
export function rotate([qx, qy, qz, qw]: number[], [vx, vy, vz]: number[]): Vec {
  const ix = qw * vx + qy * vz - qz * vy;
  const iy = qw * vy + qz * vx - qx * vz;
  const iz = qw * vz + qx * vy - qy * vx;
  const iw = -qx * vx - qy * vy - qz * vz;
  return [
    ix * qw + iw * -qx + iy * -qz - iz * -qy,
    iy * qw + iw * -qy + iz * -qx - ix * -qz,
    iz * qw + iw * -qz + ix * -qy - iy * -qx
  ];
}

/** Android world (east, north, up) → three.js (x, y-up, z toward viewer). */
export const toThree = ([x, y, z]: Vec | number[]): Vec => [x, z, -y];

/**
 * The phone model's local axes are the device axes, so its three.js
 * orientation is (world axis swap) ∘ (device → Android world): the swap is a
 * −90° turn about x, applied after the phone's own rotation.
 */
export function quatToThree([x, y, z, w]: number[]): Quat {
  const s = Math.SQRT1_2; // swap = (−s, 0, 0, s)
  return [
    s * x - s * w,
    s * y + s * z,
    s * z - s * y,
    s * w + s * x
  ];
}

/** Index of the last sample at or before `t` (−1 if none). */
export function indexAt(samples: MotionSample[], t: number): number {
  let lo = 0, hi = samples.length - 1, found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (samples[mid].t_ms <= t) { found = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return found;
}

/** How hard the phone is moving: gyro rate plus a scaled acceleration, ~0 still … 10+ violent. */
export const intensity = (s: MotionSample) => magnitude(s.g) + magnitude(s.a) / 4;

export function intensityLabel(value: number): string {
  if (value < 0.6) return 'Still';
  if (value < 2.5) return 'Moving';
  if (value < 6) return 'Moving fast';
  return 'Violent movement';
}

/** Tilt of the screen relative to upright, in degrees (pitch forward/back, roll left/right). */
export function tilt(q: number[]): { pitch: number; roll: number } {
  const up = rotate(q, [0, 1, 0]); // device "top" in world coordinates
  const pitch = Math.asin(Math.max(-1, Math.min(1, up[2]))) * (180 / Math.PI);
  const right = rotate(q, [1, 0, 0]);
  const roll = Math.asin(Math.max(-1, Math.min(1, -right[2]))) * (180 / Math.PI);
  return { pitch: Math.round(pitch), roll: Math.round(roll) };
}

/**
 * Dead-reckoned path. Phone accelerometers drift fast, so this is the *shape* of
 * the movement only: velocity is damped every step and zeroed whenever the
 * phone is still (zero-velocity update), which keeps the drift bounded.
 */
export function estimatePath(samples: MotionSample[]): Vec[] {
  const out: Vec[] = [];
  let v: Vec = [0, 0, 0];
  let p: Vec = [0, 0, 0];
  for (let i = 0; i < samples.length; i++) {
    const s = samples[i];
    const dt = i ? Math.min(0.1, (s.t_ms - samples[i - 1].t_ms) / 1000) : 0;
    const still = magnitude(s.a) < 0.25 && magnitude(s.g) < 0.15;
    if (still) v = [0, 0, 0];
    else {
      const a = rotate(s.q, s.a);
      v = [(v[0] + a[0] * dt) * 0.96, (v[1] + a[1] * dt) * 0.96, (v[2] + a[2] * dt) * 0.96];
    }
    p = [p[0] + v[0] * dt, p[1] + v[1] * dt, p[2] + v[2] * dt];
    out.push(toThree(p));
  }
  return out;
}
