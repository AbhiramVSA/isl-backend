import type { Sentence } from "../types";
import { clock } from "../format";
import { GlossChip } from "./GlossStream";
import { Badge, Empty, Panel } from "./ui";

function SentenceCard({ s }: { s: Sentence }) {
  const v = s.verification;
  return (
    <article className="sentence">
      <div className="sentence-final">{s.final_text || <span className="muted">(empty sentence)</span>}</div>
      <div className="sentence-meta">
        <Badge tone={s.source === "llm" ? "info" : "muted"} title="Which text was chosen as final">
          source {s.source}
        </Badge>
        <Badge tone={v.passed ? "good" : "warn"} title={v.reason ?? "grounding verification"}>
          {v.passed ? "verification passed" : `verification failed: ${v.reason ?? "no reason given"}`}
        </Badge>
        <span className="sentence-time">
          {clock(s.t_start_ms)} to {clock(s.t_end_ms)}
        </span>
      </div>
      <div className="sentence-cols">
        <div>
          <div className="col-title">joiner</div>
          <div className="col-text">{s.joiner_text || <span className="muted">none</span>}</div>
        </div>
        <div>
          <div className="col-title">llm</div>
          <div className="col-text">{s.llm_text ?? <span className="muted">no LLM text</span>}</div>
        </div>
      </div>
      {s.llm_error ? <div className="sentence-err">LLM error: {s.llm_error}</div> : null}
      {s.glosses.length > 0 ? (
        <div className="chips chips-small">
          {s.glosses.map((g) => (
            <GlossChip key={g.id} g={g} />
          ))}
        </div>
      ) : null}
    </article>
  );
}

export function SentencesPanel({
  sentences,
  canControl,
  onEndSentence,
  onReset,
}: {
  sentences: Sentence[] | null;
  canControl: boolean;
  onEndSentence: () => void;
  onReset: () => void;
}) {
  const list = sentences ? [...sentences].reverse() : null;
  return (
    <Panel
      title="Sentences"
      aside={
        <div className="btn-row">
          <button type="button" className="btn btn-small" disabled={!canControl} onClick={onEndSentence} title="Force a sentence boundary now">
            End sentence now
          </button>
          <button type="button" className="btn btn-small btn-quiet" disabled={!canControl} onClick={onReset} title="Clear buffers, glosses, sentences and safety state on the server">
            Reset
          </button>
        </div>
      }
    >
      {!list ? (
        <Empty>Nothing received yet.</Empty>
      ) : list.length === 0 ? (
        <Empty>No sentence completed yet. A sentence closes after a rest, or when you end it.</Empty>
      ) : (
        <div className="sentences">
          {list.map((s) => (
            <SentenceCard key={s.id} s={s} />
          ))}
        </div>
      )}
    </Panel>
  );
}
