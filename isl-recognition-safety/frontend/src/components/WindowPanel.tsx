import type { Update } from "../types";
import { ms, pct } from "../format";
import { Bar, Badge, Empty, Panel } from "./ui";

const HEAD_NAME: Record<string, string> = { hwgat: "HWGAT", include: "INCLUDE" };

export function WindowPanel({ update }: { update: Update | null }) {
  const w = update?.window ?? null;
  if (!w) {
    return (
      <Panel title="Latest window">
        <Empty>No window classified yet. A window is scored once the gate opens on a signing segment.</Empty>
      </Panel>
    );
  }
  const heads = Object.entries(w.heads);
  return (
    <Panel
      title="Latest window"
      aside={
        <span className="mono-ish">
          {ms(w.t_start_ms)} to {ms(w.t_end_ms)}, {w.frames} frames
        </span>
      }
    >
      <div className="fused">
        <div className="fused-label" title="Fused prediction across heads">
          {w.fused.label}
        </div>
        <div className="fused-meta">
          <span>p {pct(w.fused.p, 1)}</span>
          <span>margin {pct(w.fused.margin, 1)}</span>
          <Badge tone={w.fused.agreement ? "good" : "warn"} title="Whether the heads agree on the top label">
            {w.fused.agreement ? "heads agree" : "heads disagree"}
          </Badge>
        </div>
      </div>
      <div className="heads">
        {heads.map(([key, h]) => (
          <div className="head" key={key}>
            <div className="head-title">
              <span>{HEAD_NAME[key] ?? key}</span>
              <span className="head-lat">{Math.round(h.latency_ms)} ms</span>
            </div>
            {h.top.length === 0 ? (
              <Empty>no scores from this head</Empty>
            ) : (
              h.top.slice(0, 5).map((t, i) => (
                <Bar
                  key={`${t.label}-${i}`}
                  label={t.label}
                  value={t.p}
                  text={pct(t.p, 1)}
                  tone={i === 0 ? "data" : "muted"}
                />
              ))
            )}
          </div>
        ))}
      </div>
    </Panel>
  );
}
