export interface Settings {
  llmEnabled: boolean;
  minConfidence: number;
  serverSide: boolean;
  mirror: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  llmEnabled: true,
  minConfidence: 0.55,
  serverSide: false,
  mirror: true,
};

export function SettingsDrawer({
  open,
  settings,
  onChange,
  onClose,
  configSent,
}: {
  open: boolean;
  settings: Settings;
  onChange: (next: Settings) => void;
  onClose: () => void;
  configSent: boolean;
}) {
  return (
    <aside className={`drawer${open ? " open" : ""}`} aria-hidden={!open}>
      <div className="drawer-head">
        <h2>Settings</h2>
        <button type="button" className="btn btn-small btn-quiet" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="drawer-body">
        <label className="row">
          <input type="checkbox" checked={settings.llmEnabled} onChange={(e) => onChange({ ...settings, llmEnabled: e.target.checked })} />
          <span>
            <span className="row-title">LLM polish</span>
            <span className="row-sub">Sends control config llm_enabled. Off means the joiner text is final.</span>
          </span>
        </label>
        <label className="row row-col">
          <span className="row-title">
            Minimum confidence <span className="row-val">{settings.minConfidence.toFixed(2)}</span>
          </span>
          <input
            type="range"
            min={0.1}
            max={0.95}
            step={0.01}
            value={settings.minConfidence}
            onChange={(e) => onChange({ ...settings, minConfidence: Number(e.target.value) })}
          />
          <span className="row-sub">Sends control config min_confidence. Below it a sign is marked uncertain or UNKNOWN.</span>
        </label>
        <label className="row">
          <input type="checkbox" checked={settings.serverSide} onChange={(e) => onChange({ ...settings, serverSide: e.target.checked })} />
          <span>
            <span className="row-title">Server-side extraction</span>
            <span className="row-sub">Send JPEG frames (≤ 15 fps, ≤ 640 px) instead of landmarks. Video then leaves the browser to localhost.</span>
          </span>
        </label>
        <label className="row">
          <input type="checkbox" checked={settings.mirror} onChange={(e) => onChange({ ...settings, mirror: e.target.checked })} />
          <span>
            <span className="row-title">Mirror webcam</span>
            <span className="row-sub">Display only. Landmarks are sent in unmirrored image coordinates.</span>
          </span>
        </label>
        <p className="row-sub">{configSent ? "Config delivered to the server." : "Config is sent when the stream connects."}</p>
      </div>
    </aside>
  );
}
