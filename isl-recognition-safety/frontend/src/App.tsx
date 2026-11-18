import { useCallback, useEffect, useRef, useState } from "react";
import { fetchHealth } from "./api";
import { GlossStream } from "./components/GlossStream";
import { Header } from "./components/Header";
import { ModelsModal } from "./components/ModelsModal";
import { SafetyPanel } from "./components/SafetyPanel";
import { SentencesPanel } from "./components/SentencesPanel";
import { DEFAULT_SETTINGS, SettingsDrawer, type Settings } from "./components/SettingsDrawer";
import { UploadStage } from "./components/UploadStage";
import { VisionPanel } from "./components/VisionPanel";
import { WebcamStage } from "./components/WebcamStage";
import { WindowPanel } from "./components/WindowPanel";
import { useWebSocket } from "./hooks/useWebSocket";
import type { Health, Update } from "./types";

type Source = "webcam" | "upload";

export default function App() {
  const [source, setSource] = useState<Source>("webcam");
  const [cameraOn, setCameraOn] = useState(false);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [modelsOpen, setModelsOpen] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [uploadSnapshot, setUploadSnapshot] = useState<Update | null>(null);
  const [configSent, setConfigSent] = useState(false);

  const ws = useWebSocket(true);
  const wsOpen = ws.status === "open";

  // Health: fetch on mount, retry until it answers, refresh occasionally.
  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    const load = async () => {
      try {
        const h = await fetchHealth();
        if (cancelled) return;
        setHealth(h);
        setHealthError(null);
        timer = window.setTimeout(load, 30000);
      } catch (e) {
        if (cancelled) return;
        setHealthError(e instanceof Error ? e.message : String(e));
        timer = window.setTimeout(load, 5000);
      }
    };
    void load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  // Push the config whenever it changes or the socket (re)connects. The slider is debounced.
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  useEffect(() => {
    if (!wsOpen) {
      setConfigSent(false);
      return;
    }
    const t = window.setTimeout(() => {
      const ok = ws.send({
        type: "control",
        action: "config",
        llm_enabled: settingsRef.current.llmEnabled,
        min_confidence: settingsRef.current.minConfidence,
      });
      setConfigSent(ok);
    }, 150);
    return () => window.clearTimeout(t);
  }, [wsOpen, settings.llmEnabled, settings.minConfidence, ws.send]);

  const onSnapshot = useCallback((u: Update | null) => setUploadSnapshot(u), []);

  const view: Update | null = source === "webcam" ? ws.update : uploadSnapshot;
  const canControl = source === "webcam" && wsOpen;

  const switchSource = (s: Source) => {
    setSource(s);
    if (s === "upload") setCameraOn(false);
  };

  return (
    <div className="app">
      <Header
        status={ws.status}
        attempts={ws.attempts}
        hello={ws.hello}
        health={health}
        healthError={healthError}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenModels={() => setModelsOpen(true)}
      />
      {ws.lastError ? <div className="banner banner-err">Server: {ws.lastError}</div> : null}
      {health && health.device === "cpu" ? (
        <div className="banner">Backend is running on CPU. Recognition latency will be higher and the HWGAT stride is increased.</div>
      ) : null}

      <main className="main">
        <div className="col col-left">
          <div className="source">
            <div className="seg" role="tablist" aria-label="Source">
              <button type="button" role="tab" aria-selected={source === "webcam"} className={source === "webcam" ? "on" : ""} onClick={() => switchSource("webcam")}>
                Webcam
              </button>
              <button type="button" role="tab" aria-selected={source === "upload"} className={source === "upload" ? "on" : ""} onClick={() => switchSource("upload")}>
                Upload video
              </button>
            </div>
            {source === "webcam" ? (
              <button type="button" className={`btn${cameraOn ? " btn-quiet" : " btn-primary"}`} onClick={() => setCameraOn((v) => !v)}>
                {cameraOn ? "Stop camera" : "Start camera"}
              </button>
            ) : null}
          </div>
          {source === "webcam" ? (
            <WebcamStage enabled={cameraOn} serverSide={settings.serverSide} mirror={settings.mirror} wsOpen={wsOpen} send={ws.send} />
          ) : (
            <UploadStage onSnapshot={onSnapshot} />
          )}
          <VisionPanel update={view} />
        </div>

        <div className="col col-mid">
          <WindowPanel update={view} />
          <GlossStream glosses={view ? view.glosses : null} live={source === "webcam"} />
          <SentencesPanel
            sentences={view ? view.sentences : null}
            canControl={canControl}
            onEndSentence={() => ws.send({ type: "control", action: "end_sentence" })}
            onReset={() => ws.send({ type: "control", action: "reset" })}
          />
        </div>

        <div className="col col-right">
          <SafetyPanel safety={view ? view.safety : null} events={view ? view.safety_events : null} />
        </div>
      </main>

      <SettingsDrawer open={settingsOpen} settings={settings} onChange={setSettings} onClose={() => setSettingsOpen(false)} configSent={configSent} />
      {settingsOpen ? <div className="drawer-backdrop" onClick={() => setSettingsOpen(false)} role="presentation" /> : null}
      <ModelsModal open={modelsOpen} onClose={() => setModelsOpen(false)} />
    </div>
  );
}
