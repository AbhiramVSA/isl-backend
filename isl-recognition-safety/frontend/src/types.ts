// Types mirroring docs/api-contract.md exactly. Do not add fields the server does not send.

export type Device = "cuda" | "cpu";

export interface ModelStatus {
  loaded: boolean;
  error: string | null;
  vocab_size?: number;
  license?: string;
  name: string;
}

export type ModelKey = "hwgat" | "include" | "stgcnpp" | "holistic";

export type ModelsStatus = Record<string, ModelStatus | undefined>;

export interface LlmStatus {
  provider: "anthropic" | "ollama" | "none";
  available: boolean;
  model: string | null;
  error: string | null;
}

export interface Health {
  status: string;
  device: Device;
  torch: string;
  mediapipe: string;
  models: ModelsStatus;
  llm: LlmStatus;
}

// ---- /api/models ----
export interface ModelCard {
  name: string;
  vocab: string[];
  dataset: string;
  license: string;
  reported_accuracy: string;
  limitations: string | string[];
}

export interface ModelCards {
  hwgat?: ModelCard;
  include?: ModelCard;
  stgcnpp?: ModelCard;
  safety_lexicon?: Record<string, string[]>;
}

// ---- shared objects ----
export type GlossStatus = "confident" | "uncertain" | "unknown";

export interface Gloss {
  id: number;
  label: string;
  display: string;
  p: number;
  status: GlossStatus;
  t_start_ms: number;
  t_end_ms: number;
  heads: Record<string, number>;
  safety_lexicon: string | null;
}

export interface Verification {
  passed: boolean;
  reason: string | null;
}

export interface Sentence {
  id: number;
  glosses: Gloss[];
  joiner_text: string;
  llm_text: string | null;
  final_text: string;
  source: "llm" | "joiner";
  verification: Verification;
  llm_error: string | null;
  t_start_ms: number;
  t_end_ms: number;
}

export type SafetyStatus = "NORMAL" | "WATCH" | "WARNING" | "CRITICAL";

export interface SafetySignal {
  key: string;
  label: string;
  value: number;
  unit: "p" | "s";
  active: boolean;
  reason: string;
}

export interface SafetyTracks {
  fall: "NORMAL" | "SUSPECT" | "FALLEN" | "RECOVERING";
  long_lie: boolean;
  distress: "NONE" | "WARNING" | "CRITICAL";
  abnormal_motion: boolean;
}

export interface Posture {
  lying: boolean;
  upright: boolean;
  torso_angle_deg: number;
  speed: number;
  immobile_s: number;
  person_present: boolean;
}

export interface LabelP {
  label: string;
  p: number;
}

export interface ActionHead {
  top: LabelP[];
  valid: boolean;
}

export type HandPose = "OPEN_PALM" | "THUMB_TUCKED" | "FIST" | "OTHER" | "NONE";

export interface GestureState {
  state: HandPose;
  stage?: number;
  cycles: number;
  waving: boolean;
  hand?: string | null;
  left?: HandPose;
  right?: HandPose;
  sequence?: string[];
}

export interface SafetyState {
  status: SafetyStatus;
  score: number;
  signals: SafetySignal[];
  tracks: SafetyTracks;
  posture: Posture;
  action: ActionHead;
  gesture: GestureState;
  reasons: string[];
}

export interface SafetyEvent {
  id: number;
  t_ms: number;
  severity: "WATCH" | "WARNING" | "CRITICAL";
  key: string;
  title: string;
  evidence: string[];
  cleared_t_ms: number | null;
}

// ---- update snapshot ----
export interface VisionInfo {
  pose: boolean;
  left_hand: boolean;
  right_hand: boolean;
  face: boolean;
  fps_in: number;
  quality: number;
}

export interface GateInfo {
  state: "ACTIVE" | "IDLE";
  energy: number;
  segment_ms: number;
  rest_ms: number;
}

export interface HeadResult {
  top: LabelP[];
  latency_ms: number;
}

export interface FusedResult {
  label: string;
  p: number;
  margin: number;
  agreement: boolean;
}

export interface WindowResult {
  t_start_ms: number;
  t_end_ms: number;
  frames: number;
  heads: Record<string, HeadResult>;
  fused: FusedResult;
}

export interface Update {
  type: "update";
  t_ms: number;
  vision: VisionInfo;
  gate: GateInfo;
  window: WindowResult | null;
  glosses: Gloss[];
  sentences: Sentence[];
  safety: SafetyState;
  safety_events: SafetyEvent[];
}

export interface Hello {
  type: "hello";
  session_id: string;
  device: Device;
  models: ModelsStatus;
  llm: LlmStatus;
}

export interface ServerError {
  type: "error";
  message: string;
}

export type ServerMessage = Hello | Update | ServerError;

// ---- client -> server ----
export type PoseArray = [number, number, number, number][]; // 33 x [x,y,z,visibility]
export type HandArray = [number, number, number][]; // 21 x [x,y,z]

export interface LandmarksMessage {
  type: "landmarks";
  t_ms: number;
  width: number;
  height: number;
  pose: PoseArray | null;
  left_hand: HandArray | null;
  right_hand: HandArray | null;
  face?: boolean;
}

export interface FrameMessage {
  type: "frame";
  t_ms: number;
  jpeg: string;
}

export type ControlMessage =
  | { type: "control"; action: "reset" }
  | { type: "control"; action: "end_sentence" }
  | { type: "control"; action: "config"; llm_enabled?: boolean; min_confidence?: number };

export type ClientMessage = LandmarksMessage | FrameMessage | ControlMessage;

// ---- /api/analyze ----
export interface LandmarkFrame {
  t_ms: number;
  pose: PoseArray | null;
  left_hand: HandArray | null;
  right_hand: HandArray | null;
}

export interface AnalyzeResult {
  duration_s: number;
  fps: number;
  frames: number;
  width: number;
  height: number;
  timeline: Update[];
  glosses: Gloss[];
  sentences: Sentence[];
  safety: SafetyState;
  safety_events: SafetyEvent[];
  landmark_frames?: LandmarkFrame[];
}

export type JobState = "queued" | "running" | "done" | "error";

export interface AnalyzeJob {
  job_id: string;
  state: JobState;
  progress: number;
  error: string | null;
  result?: AnalyzeResult;
}

export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "closed";
