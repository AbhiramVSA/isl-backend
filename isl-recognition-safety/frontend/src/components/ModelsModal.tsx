import { useEffect, useMemo, useState } from "react";
import { fetchModels } from "../api";
import type { ModelCard, ModelCards } from "../types";
import { Empty } from "./ui";

const KEYS: (keyof ModelCards)[] = ["hwgat", "include", "stgcnpp"];

function Card({ id, card, query }: { id: string; card: ModelCard; query: string }) {
  const vocab = card.vocab ?? [];
  const q = query.trim().toLowerCase();
  const shown = useMemo(() => (q ? vocab.filter((w) => w.toLowerCase().includes(q)) : vocab), [vocab, q]);
  const [expanded, setExpanded] = useState(false);
  const limit = expanded ? shown.length : 120;
  const limitations = Array.isArray(card.limitations) ? card.limitations : [card.limitations];
  return (
    <section className="model-card">
      <h3>
        {card.name} <span className="model-id">{id}</span>
      </h3>
      <dl className="model-facts">
        <dt>dataset</dt>
        <dd>{card.dataset}</dd>
        <dt>license</dt>
        <dd>{card.license}</dd>
        <dt>reported accuracy</dt>
        <dd>{card.reported_accuracy}</dd>
        <dt>vocabulary</dt>
        <dd>{vocab.length} classes</dd>
      </dl>
      {limitations.filter(Boolean).length > 0 ? (
        <ul className="model-limits">
          {limitations.filter(Boolean).map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      ) : null}
      <div className="vocab">
        <div className="vocab-head">
          {q ? `${shown.length} of ${vocab.length} match` : `${vocab.length} classes`}
          {shown.length > limit ? (
            <button type="button" className="btn btn-small btn-quiet" onClick={() => setExpanded(true)}>
              show all
            </button>
          ) : null}
        </div>
        <div className="vocab-list">
          {shown.slice(0, limit).map((w, i) => (
            <span key={`${w}-${i}`}>{w}</span>
          ))}
        </div>
      </div>
    </section>
  );
}

export function ModelsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [cards, setCards] = useState<ModelCards | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open || cards) return;
    let cancelled = false;
    setError(null);
    fetchModels()
      .then((c) => {
        if (!cancelled) setCards(c);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [open, cards]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  const lexicon = cards?.safety_lexicon;
  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="models-title" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2 id="models-title">Models and limitations</h2>
          <input
            className="search"
            type="search"
            placeholder="Search vocabulary"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search vocabulary"
          />
          <button type="button" className="btn btn-small btn-quiet" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="modal-body">
          {error ? (
            <Empty>Could not load /api/models: {error}</Empty>
          ) : !cards ? (
            <Empty>Loading model cards…</Empty>
          ) : (
            <>
              {KEYS.map((k) => {
                const c = cards[k];
                return c && typeof c === "object" && "name" in c ? <Card key={k} id={k} card={c as ModelCard} query={query} /> : null;
              })}
              {lexicon ? (
                <section className="model-card">
                  <h3>Safety lexicon</h3>
                  <p className="row-sub">Recognised glosses that raise a safety signal, mapped to vocabulary entries.</p>
                  <dl className="model-facts">
                    {Object.entries(lexicon).map(([k, words]) => (
                      <div key={k} className="fact-pair">
                        <dt>{k}</dt>
                        <dd>{words.join(", ")}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              ) : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
