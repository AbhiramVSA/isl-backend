import type { Update } from "../types";
import { fixed, ms, pct } from "../format";
import { Dot, Empty, Kv, Panel } from "./ui";

export function VisionPanel({ update }: { update: Update | null }) {
  if (!update) {
    return (
      <Panel title="What the vision model sees">
        <Empty>No frames processed yet. Start the webcam or upload a video.</Empty>
      </Panel>
    );
  }
  const { vision, gate } = update;
  const active = gate.state === "ACTIVE";
  return (
    <Panel
      title="What the vision model sees"
      aside={<span className="mono-ish">t {ms(update.t_ms)}</span>}
    >
      <div className="presence">
        <Dot on={vision.pose} label="pose" />
        <Dot on={vision.left_hand} label="left hand" />
        <Dot on={vision.right_hand} label="right hand" />
        <Dot on={vision.face} label="face" />
      </div>
      <div className="kv-grid">
        <Kv k="input fps" v={fixed(vision.fps_in, 1)} />
        <Kv k="quality" v={pct(vision.quality)} />
        <Kv k="segment" v={ms(gate.segment_ms)} />
        <Kv k="rest" v={ms(gate.rest_ms)} />
      </div>
      <div className={`gate ${active ? "gate-active" : "gate-idle"}`}>
        <div className="gate-head">
          <span className="gate-state">{gate.state}</span>
          <span className="gate-energy">energy {fixed(gate.energy, 2)}</span>
        </div>
        <div className="meter">
          <div className="meter-fill" style={{ width: `${Math.min(100, Math.max(0, gate.energy * 100))}%` }} />
        </div>
        <div className="gate-note">{active ? "signing segment open" : "waiting for motion"}</div>
      </div>
    </Panel>
  );
}
