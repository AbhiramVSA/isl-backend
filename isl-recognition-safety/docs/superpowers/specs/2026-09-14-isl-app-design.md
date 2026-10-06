# ISL Recognition + Safety Monitor — Design Spec (2026-09-14)

Status: approved for implementation under the user's standing instruction to research, decide and build autonomously. Research inputs live in `docs/research/`.

## 1. Goal

A locally runnable web application that:

1. Takes live webcam input or an uploaded video.
2. Extracts body/hand/face landmarks with a pretrained model.
3. Recognises isolated Indian Sign Language (ISL) signs from continuous signing using pretrained ISL models only (no training).
4. Converts the recognised gloss sequence into an English sentence without inventing content for unrecognised signs.
5. In parallel, detects observable safety events (fall, lying + immobility, staggering, frantic movement, Signal-for-Help gesture, help/danger signs) with evidence-backed alerts.
6. Exposes every intermediate: landmarks seen, per-window predictions and confidences, raw gloss stream, final sentence, safety signals, fusion state and reasons.

## 2. Model selection (from research)

| Role | Selected | Why | Alternatives rejected |
|---|---|---|---|
| Landmarks (server) | MediaPipe Tasks `HolisticLandmarker` 1.0.1, CPU, Apache-2.0 | 30 ms/frame on CPU, same layout the SLR models were trained on, GPU delegate unavailable on Windows Python anyway | rtmlib/RTMW (4× slower on CPU, GPU-only value), YOLO-pose (AGPL, no hands), Sapiens (too heavy), OpenPose (dead) |
| Landmarks (browser) | `@mediapipe/tasks-vision@1.0.1` HolisticLandmarker, WebGL delegate | Raw video never leaves the browser for the webcam path; same landmark layout as the server | — |
| ISL words, primary | **HWGAT** (RKMVERI, MIT), FDMSE-ISL, **2,002 words**, 20.5 M params | Only ISL model with a signer-independent evaluation (93.9% top-1, 20 Deaf signers); public weights; pure PyTorch; 43 ms/clip on RTX 3060 fp32, 21 ms fp16, ~800 ms CPU | — |
| ISL words, second opinion | **INCLUDE transformer (large)** AI4Bharat, MIT, 263 words | Independent model trained on a different corpus (IIT Madras INCLUDE); checkpoint val score 0.835; reimplemented in plain PyTorch and verified bit-exact against the reference (its inference-time dropout removed) | OpenHands SL-GCN (93.5% on INCLUDE) is better on paper but its class order depends on a split CSV that is not in the repo; pursued only if the Zenodo pose archive recovers it |
| Fingerspelling | Not shipped in v1 | Every candidate is a still-image classifier trained on studio photos (Kaggle ISL alphabet) with no evidence of webcam transfer; shipping it would be pretending | Hemg ViT (Apache-2.0), landmark .h5/.tflite models |
| Action / fall event | **ST-GCN++** pyskl NTU-60 xsub HRNet joint checkpoint, standalone torch reimplementation (verified strict load, 63 ms/clip CPU) | Only pretrained model that separates *falling* and *staggering* from sitting/picking up; classes A41–A49 give medical cues | VideoMAE/TimeSformer (no fall class, NC license), X-CLIP zero-shot (unreliable), YOLO fall weights (unknown provenance) |
| Posture / immobility | Geometric rules on pose landmarks | Explainable, cheap, gates the GCN | — |
| Distress gesture | Hand-landmark finite-state machine (Signal for Help, waving) | No public weights exist; the gesture is defined geometrically | HaGRID (AGPL YOLO route) |
| Help/danger signs | Recognised HWGAT glosses in a safety lexicon (Help, Dangerous, Police, Pain, Hurt, Ambulance, Fire, Attack, Sick, Accident, Urgent, …) | Direct linguistic evidence | — |
| Gloss → sentence | Deterministic ISL-grammar joiner always; optional Claude (`claude-opus-5`) polish with grounding verification; optional Ollama for offline | Only glosses + confidences leave the machine; verification guarantees no invented content words | Fine-tuned gloss2text models (none for ISL) |

## 3. Architecture

```
Browser (React + Vite + TS)                    Server (FastAPI, Python 3.12)
┌──────────────────────────────┐   WebSocket   ┌──────────────────────────────────────┐
│ webcam → HolisticLandmarker  │ landmarks/    │ SessionPipeline (one per socket)     │
│ (WebGL) → 543×(x,y,z,vis)    │ frame JSON  → │  LandmarkFrame buffer (ring, ~10 s)  │
│ or JPEG frames (fallback)    │               │  ├─ SignRecognizer (gate+window)     │
│ upload → POST /api/analyze   │  ← events     │  │   ├─ HWGAT head                    │
│ UI: video, skeleton overlay, │   (JSON)      │  │   └─ INCLUDE head                  │
│ predictions, gloss stream,   │               │  │   → GlossEmitter (smooth/debounce) │
│ sentence, safety panel       │               │  ├─ SafetyMonitor                    │
└──────────────────────────────┘               │  │   ├─ PostureRules                  │
                                               │  │   ├─ STGCNpp action head           │
                                               │  │   ├─ GestureFSM                    │
                                               │  │   └─ Fusion state machine          │
                                               │  └─ SentenceBuilder                  │
                                               │      ├─ Joiner (deterministic)       │
                                               │      └─ LLMPolisher + Verifier       │
                                               │ Uploads: VideoDecoder → server       │
                                               │ HolisticLandmarker → same pipeline   │
                                               └──────────────────────────────────────┘
```

Both input paths feed the same `SessionPipeline.process(LandmarkFrame)`; only landmark extraction differs (browser vs server).

## 4. Components

### 4.1 `LandmarkFrame`
`t_ms`, `width`, `height`, `pose` (33×4: x,y,z,visibility, normalised 0–1), `left_hand` (21×3), `right_hand` (21×3), `face` (optional, 468×3, not used by v1 heads), plus `present` flags. Missing parts are `None`.

### 4.2 `SigningGate`
Per frame: hand presence, wrist height relative to hips/shoulders, motion energy (sum of hand landmark displacement normalised by shoulder width and dt, 5-frame median). Hysteresis: ACTIVE after energy > θ_hi for 3 frames with a hand present; IDLE after energy < θ_lo for 8 frames or hands absent 5 frames. Emits `segment_start`, `segment_end`, and `rest_since`.

### 4.3 `SignRecognizer`
- Maintains a trailing landmark buffer. Every `stride` ms (default 400) while ACTIVE and buffer ≥ 0.6 s: build a window covering the current active segment (up to 4 s), preprocess for each head, run both heads (GPU if available), produce per-head top-5 with probabilities.
- HWGAT preprocessing ported from the MIT demo: pixel scaling, 29-keypoint select, hand-correction spline fill, nose/shoulder normalisation, 192-frame temporal sample (centre-pad by replicating first/last frame), 4-window (64 kp) assembly.
- INCLUDE preprocessing: 25 pose + 2 hands x,y in 1920×1080 pixel space, NaN interpolation, zero-pad to 169.
- Fusion: HWGAT is the primary vote. INCLUDE agreement (same lemma) adds confidence; disagreement lowers it. Scores are exposed separately in the UI.

### 4.4 `GlossEmitter`
EMA on the primary probability vector (α=0.6). Emit a gloss when the same top-1 has held for K=2 consecutive windows with p ≥ τ_high (0.55) and margin ≥ 0.15; emit `UNKNOWN` when a segment ends without a stable prediction but had p_max < τ_low (0.35) or margin < 0.08 throughout; emit `word(?)` (low-confidence marker) for 0.35–0.55. One emission per active segment (rising edge), re-armed when the gate goes IDLE. Sentence boundary when IDLE ≥ 1.2 s after at least one gloss, or 12 glosses.

### 4.5 `SentenceBuilder`
- `Joiner`: SOV→SVO heuristics, pronoun normalisation, copula insertion, sentence-final WH fronting, NOT handling, UNKNOWN → `[unknown sign]`, `word(?)` preserved.
- `LLMPolisher` (optional, provider `anthropic` | `ollama` | `none`): strict system prompt, JSON schema output `{ok, sentence, used_glosses}`, `max_tokens` 300, effort low. Input = gloss tokens + confidences only.
- `Verifier`: lemmatised output tokens ⊆ gloss lemmas ∪ function-word allowlist ∪ punctuation; every content gloss present; `[unknown sign]` count preserved; else fall back to the joiner and record `verification_failed`.

### 4.6 `SafetyMonitor`
- `PostureRules` per frame: COCO-17 mapping from MediaPipe pose; torso angle, bbox W/H, head height, hip vertical velocity, mean joint speed, keypoint quality; EMA α=0.3; flags `lying`, `upright`, `sudden_drop`, `frantic`, `immobile_for_s`, `person_absent`.
- `ActionHead` (ST-GCN++): every 500 ms on the last 100 frames (looped if fewer), only if quality ≥ 0.7 on ≥ 80% frames; outputs p_fall, p_stagger, p_medical, p_wave with 5-vote majority smoothing.
- `GestureFSM`: Signal for Help (OPEN_PALM → THUMB_TUCKED → FIST within 2.5 s, each ≥ 4 frames; 1 cycle WARNING, 2 CRITICAL) and help-waving (wrist above shoulder, ≥ 3 x sign changes in 2 s).
- `SignLexicon`: glosses in the safety lexicon with p ≥ 0.6; repeated HELP raises severity.
- `Fusion`: tracks `fall`, `long_lie`, `distress`, `abnormal_motion` with the hysteresis/state machine from `docs/research/safety-detection.md`; overall status NORMAL / WATCH / WARNING / CRITICAL; every active signal carries a probability or duration and a human-readable reason; 30 s cooldown per event; timers freeze on `person_absent`.

### 4.7 API
- `GET /api/health` — model load status, device, versions, LLM provider status.
- `GET /api/models` — vocabularies, licences, limitations.
- `WS /ws/stream` — client sends `{type:"landmarks", ...}` or `{type:"frame", jpeg:base64}` or `{type:"control", action:"reset"|"end_sentence"}`; server sends `{type:"update", ...}` snapshots at ≤ 10 Hz containing gate state, latest window predictions per head, gloss stream, sentence(s), safety status/signals, and `{type:"error", message}`.
- `POST /api/analyze` — multipart video; server decodes with OpenCV, runs HolisticLandmarker at native fps (capped at 30 fps, downscaled to ≤ 640 px wide), pushes frames through a fresh `SessionPipeline`, returns the full timeline plus the final sentence and safety events; streams progress over `WS /ws/analyze/{job}` optional in v1 (polling `GET /api/analyze/{job}`).

### 4.8 Frontend
Single page: source selector (webcam / upload), video with skeleton overlay, "what the vision model sees" panel (landmark presence, gate state, motion energy), per-head prediction bars, raw gloss stream with confidence chips and UNKNOWN markers, sentence card (joiner text + polished text + verification badge), safety panel (status, signals with percentages/durations, reasons, timeline). Settings: LLM on/off, thresholds, browser vs server extraction.

## 5. Error handling and robustness
- Every model loads lazily behind a registry; a missing checkpoint disables only that head and is reported in `/api/health` and the UI banner; the app never crashes on missing models.
- CUDA unavailable → CPU with a visible notice; HWGAT stride automatically increased to keep CPU load bounded.
- LLM missing key / network failure → joiner output only, badge "LLM unavailable".
- WebSocket messages validated with Pydantic; malformed input → error message, connection kept.
- Uploads limited to 200 MB, decode failures reported.

## 6. Testing
- Unit: preprocessing shape/normalisation, joiner grammar cases, verifier accept/reject, gate hysteresis, gloss emitter debounce/UNKNOWN, safety fusion transitions on synthetic pose sequences, ST-GCN++ and HWGAT strict loading.
- Integration: run real INCLUDE clips (Zenodo CC BY 4.0) through `POST /api/analyze` and report top-1/top-5 hits per head; synthetic fall sequences through the safety monitor; WebSocket round trip with recorded landmark frames.
- Manual: webcam session in the browser.

## 7. Known limitations (to document, not hide)
- HWGAT vocabulary is the FDMSE dictionary (2,002 citation-form words); regional variants and continuous coarticulated signing are out of its training distribution; all evaluation numbers are on isolated clips.
- INCLUDE model is signer-dependent and expects 1920×1080 framing.
- Safety detection is heuristic + a skeleton action model trained on NTU RGB+D (lab data); it cannot infer intent or mental state and must not be treated as a medical or emergency system.
- No fingerspelling in v1.
