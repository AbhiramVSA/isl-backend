export const pct = (p: number | null | undefined, digits = 0): string =>
  p == null || Number.isNaN(p) ? "–" : `${(p * 100).toFixed(digits)}%`;

export const fixed = (v: number | null | undefined, digits = 1): string =>
  v == null || Number.isNaN(v) ? "–" : v.toFixed(digits);

export const ms = (v: number | null | undefined): string => {
  if (v == null || Number.isNaN(v)) return "–";
  if (v < 1000) return `${Math.round(v)} ms`;
  return `${(v / 1000).toFixed(1)} s`;
};

export const clock = (tMs: number): string => {
  const s = Math.max(0, tMs) / 1000;
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r.toFixed(1).padStart(4, "0")}`;
};

/** Index of the element whose `t_ms` is nearest to `t` (array sorted by t_ms), or -1 when empty. */
export function nearestByTime<T extends { t_ms: number }>(items: readonly T[], t: number): number {
  if (items.length === 0) return -1;
  let lo = 0;
  let hi = items.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (items[mid]!.t_ms < t) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0) {
    const a = items[lo - 1]!.t_ms;
    const b = items[lo]!.t_ms;
    if (Math.abs(a - t) <= Math.abs(b - t)) return lo - 1;
  }
  return lo;
}
