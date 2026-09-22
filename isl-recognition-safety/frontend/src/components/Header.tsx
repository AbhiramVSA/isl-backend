import type { ConnectionStatus, Health, Hello, LlmStatus, ModelsStatus } from "../types";
import { Badge } from "./ui";

const MODEL_ORDER = ["hwgat", "include", "slgcn", "stgcnpp", "holistic"];
const SHORT: Record<string, string> = {
  hwgat: "HWGAT",
  include: "INCLUDE",
  slgcn: "SL-GCN",
  stgcnpp: "ST-GCN++",
  holistic: "Holistic",
};

function connectionLabel(s: ConnectionStatus, attempts: number): string {
  switch (s) {
    case "open":
      return "connected";
    case "connecting":
      return "connecting…";
    case "reconnecting":
      return attempts > 0 ? `reconnecting (try ${attempts})` : "reconnecting…";
    case "closed":
      return "closed";
  }
}

function ModelBadges({ models }: { models: ModelsStatus }) {
  const keys = [...MODEL_ORDER.filter((k) => k in models), ...Object.keys(models).filter((k) => !MODEL_ORDER.includes(k))];
  return (
    <>
      {keys.map((k) => {
        const m = models[k];
        if (!m) return null;
        const label = SHORT[k] ?? k;
        const tip = m.loaded
          ? `${m.name}${m.vocab_size ? `, ${m.vocab_size} classes` : ""}${m.license ? `, ${m.license}` : ""}`
          : `${m.name}: ${m.error ?? "not loaded"}`;
        return (
          <Badge key={k} tone={m.loaded ? "good" : "crit"} title={tip}>
            {label} {m.loaded ? "loaded" : "error"}
          </Badge>
        );
      })}
    </>
  );
}

function LlmBadge({ llm }: { llm: LlmStatus }) {
  if (llm.provider === "none") return <Badge tone="muted" title="No LLM configured; joiner text is used as-is">LLM off</Badge>;
  const tip = llm.available
    ? `${llm.provider}${llm.model ? `, ${llm.model}` : ""}`
    : `${llm.provider}: ${llm.error ?? "unavailable"}`;
  return (
    <Badge tone={llm.available ? "info" : "warn"} title={tip}>
      LLM {llm.provider}
      {llm.available ? "" : " unavailable"}
    </Badge>
  );
}

export function Header({
  status,
  attempts,
  hello,
  health,
  healthError,
  onOpenSettings,
  onOpenModels,
}: {
  status: ConnectionStatus;
  attempts: number;
  hello: Hello | null;
  health: Health | null;
  healthError: string | null;
  onOpenSettings: () => void;
  onOpenModels: () => void;
}) {
  const models = hello?.models ?? health?.models ?? null;
  const llm = hello?.llm ?? health?.llm ?? null;
  const device = hello?.device ?? health?.device ?? null;
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-name">ISL pipeline inspector</span>
        <span className="brand-sub">sign recognition and safety monitoring, every intermediate shown</span>
      </div>
      <div className="status-row">
        <span className={`conn conn-${status}`} title="WebSocket /ws/stream">
          <i />
          {connectionLabel(status, attempts)}
        </span>
        {device ? (
          <Badge tone={device === "cuda" ? "info" : "warn"} title={health ? `torch ${health.torch}, mediapipe ${health.mediapipe}` : undefined}>
            {device}
          </Badge>
        ) : (
          <Badge tone="muted" title={healthError ?? "waiting for /api/health"}>
            device unknown
          </Badge>
        )}
        {models ? <ModelBadges models={models} /> : <Badge tone="muted">models: waiting for server</Badge>}
        {llm ? <LlmBadge llm={llm} /> : null}
      </div>
      <div className="topbar-actions">
        <button type="button" className="btn" onClick={onOpenModels}>
          Models and limitations
        </button>
        <button type="button" className="btn" onClick={onOpenSettings}>
          Settings
        </button>
      </div>
    </header>
  );
}
