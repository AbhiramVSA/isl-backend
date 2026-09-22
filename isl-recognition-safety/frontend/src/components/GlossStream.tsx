import type { Gloss } from "../types";
import { clock, pct } from "../format";
import { Empty, Panel } from "./ui";

function tooltip(g: Gloss): string {
  const heads = Object.entries(g.heads)
    .map(([k, p]) => `${k} ${pct(p, 1)}`)
    .join(", ");
  const lines = [
    `${g.label} (${g.status}) p=${pct(g.p, 1)}`,
    heads ? `heads: ${heads}` : "heads: none reported",
    `${clock(g.t_start_ms)} to ${clock(g.t_end_ms)} (${g.t_end_ms - g.t_start_ms} ms)`,
  ];
  if (g.safety_lexicon) lines.push(`safety lexicon: ${g.safety_lexicon}`);
  return lines.join("\n");
}

export function GlossChip({ g }: { g: Gloss }) {
  const text = g.status === "unknown" ? "UNKNOWN" : g.status === "uncertain" ? `${g.display}(?)` : g.display;
  return (
    <span className={`chip chip-${g.status}`} title={tooltip(g)}>
      {g.safety_lexicon ? (
        <span className="chip-warn" aria-label={`safety lexicon ${g.safety_lexicon}`}>
          !
        </span>
      ) : null}
      <span className="chip-text">{text}</span>
      <span className="chip-p">{pct(g.p)}</span>
    </span>
  );
}

export function GlossStream({ glosses, live }: { glosses: Gloss[] | null; live: boolean }) {
  return (
    <Panel
      title="Recognised sign sequence"
      aside={<span className="mono-ish">{glosses ? `${glosses.length} in buffer` : ""}</span>}
    >
      {!glosses ? (
        <Empty>Nothing received yet.</Empty>
      ) : glosses.length === 0 ? (
        <Empty>{live ? "No sign emitted for the current sentence yet." : "No sign in the buffer at this point of the video."}</Empty>
      ) : (
        <div className="chips">
          {glosses.map((g) => (
            <GlossChip key={g.id} g={g} />
          ))}
        </div>
      )}
      <div className="legend">
        <span className="chip chip-confident chip-mini">confident</span>
        <span className="chip chip-uncertain chip-mini">word(?)</span>
        <span className="chip chip-unknown chip-mini">UNKNOWN</span>
        <span className="legend-note">hover a chip for per-head probabilities and timing</span>
      </div>
    </Panel>
  );
}
