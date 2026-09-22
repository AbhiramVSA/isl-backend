import { useState } from "react";
import type { SafetyEvent, SafetySignal, SafetyState } from "../types";
import { clock, fixed, pct } from "../format";
import { Bar, Badge, Empty, Kv, Panel } from "./ui";

type Tone = "muted" | "info" | "warn" | "crit";
const STATUS_TONE: Record<SafetyState["status"], Tone> = {
  NORMAL: "muted",
  WATCH: "info",
  WARNING: "warn",
  CRITICAL: "crit",
};
const SEVERITY_TONE: Record<SafetyEvent["severity"], Tone> = { WATCH: "info", WARNING: "warn", CRITICAL: "crit" };

function signalValue(s: SafetySignal): string {
  return s.unit === "p" ? pct(s.value) : `${fixed(s.value, 1)} s`;
}

function SignalRow({ s }: { s: SafetySignal }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`signal${s.active ? " signal-active" : ""}`}>
      <button type="button" className="signal-main" onClick={() => setOpen((o) => !o)} title={s.reason}>
        <span className="signal-flag" aria-hidden />
        <span className="signal-label">{s.label}</span>
        <span className="signal-value">{signalValue(s)}</span>
        <span className="signal-state">{s.active ? "active" : "quiet"}</span>
      </button>
      {open ? <div className="signal-reason">{s.reason || "no reason reported"}</div> : null}
    </div>
  );
}

function EventLog({ events }: { events: SafetyEvent[] }) {
  if (events.length === 0) return <Empty>No safety event recorded.</Empty>;
  const list = [...events].reverse();
  return (
    <ol className="events">
      {list.map((e) => (
        <li key={e.id} className={`event tone-${SEVERITY_TONE[e.severity]}${e.cleared_t_ms != null ? " event-cleared" : ""}`}>
          <div className="event-head">
            <Badge tone={SEVERITY_TONE[e.severity]}>{e.severity}</Badge>
            <span className="event-title">{e.title}</span>
            <span className="event-time">
              {clock(e.t_ms)}
              {e.cleared_t_ms != null ? ` cleared ${clock(e.cleared_t_ms)}` : ""}
            </span>
          </div>
          {e.evidence.length > 0 ? (
            <ul className="evidence">
              {e.evidence.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

export function SafetyPanel({ safety, events }: { safety: SafetyState | null; events: SafetyEvent[] | null }) {
  if (!safety) {
    return (
      <Panel title="Safety">
        <Empty>No safety state received yet.</Empty>
      </Panel>
    );
  }
  const tone = STATUS_TONE[safety.status];
  const { posture, action, gesture, tracks } = safety;
  return (
    <Panel title="Safety" className="panel-safety">
      <div className={`safety-status tone-${tone}${safety.status === "CRITICAL" ? " pulse" : ""}`}>
        <span className="safety-pill">{safety.status}</span>
        <span className="safety-score">score {pct(safety.score)}</span>
      </div>
      <div className="meter meter-safety">
        <div className="meter-fill" style={{ width: `${Math.min(100, Math.max(0, safety.score * 100))}%` }} />
      </div>

      {safety.reasons.length > 0 ? (
        <ul className="reasons">
          {safety.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      ) : (
        <Empty>No reason raised.</Empty>
      )}

      <h3 className="sub">Signals</h3>
      {safety.signals.length === 0 ? (
        <Empty>No signal reported.</Empty>
      ) : (
        <div className="signals">
          {safety.signals.map((s) => (
            <SignalRow key={s.key} s={s} />
          ))}
        </div>
      )}

      <h3 className="sub">Tracks</h3>
      <div className="kv-grid">
        <Kv k="fall" v={tracks.fall} />
        <Kv k="distress" v={tracks.distress} />
        <Kv k="long lie" v={tracks.long_lie ? "yes" : "no"} />
        <Kv k="abnormal motion" v={tracks.abnormal_motion ? "yes" : "no"} />
      </div>

      <h3 className="sub">Posture</h3>
      <div className="kv-grid">
        <Kv k="person present" v={posture.person_present ? "yes" : "no"} />
        <Kv k="torso angle" v={`${fixed(posture.torso_angle_deg, 0)}°`} />
        <Kv k="speed" v={fixed(posture.speed, 2)} />
        <Kv k="immobile" v={`${fixed(posture.immobile_s, 1)} s`} />
        <Kv k="upright" v={posture.upright ? "yes" : "no"} />
        <Kv k="lying" v={posture.lying ? "yes" : "no"} />
      </div>

      <h3 className="sub">
        Action head <span className="sub-note">{action.valid ? "valid" : "not valid for this window"}</span>
      </h3>
      {action.top.length === 0 ? (
        <Empty>No action scores yet.</Empty>
      ) : (
        action.top.slice(0, 3).map((t, i) => <Bar key={`${t.label}-${i}`} label={t.label} value={t.p} text={pct(t.p, 1)} tone={action.valid ? "data" : "muted"} />)
      )}

      <h3 className="sub">Gesture</h3>
      <div className="kv-grid">
        <Kv k="left hand" v={gesture.left ?? "NONE"} />
        <Kv k="right hand" v={gesture.right ?? "NONE"} />
        <Kv k="Signal-for-Help stage" v={`${gesture.stage ?? 0}/3 ${(gesture.sequence ?? []).join(" → ") || "(show an open palm to start)"}`} />
        <Kv k="cycles (8 s)" v={gesture.cycles} />
        <Kv k="waving" v={gesture.waving ? "yes" : "no"} />
      </div>

      <h3 className="sub">Event log</h3>
      {events ? <EventLog events={events} /> : <Empty>No events received.</Empty>}
    </Panel>
  );
}
