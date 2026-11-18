# How the pipelines work

Both input paths (live webcam, uploaded video) produce the same `LandmarkFrame` stream and feed the same `SessionPipeline` (`backend/app/pipeline.py`). Only landmark extraction differs:

| Path | Extraction | Where video goes |
|---|---|---|
| Webcam (default) | MediaPipe `HolisticLandmarker` in the browser (`@mediapipe/tasks-vision` 1.0.1, WebGL) | Never leaves the browser; only 33 pose + 2×21 hand landmarks (~6 KB/frame) are sent over the WebSocket |
| Webcam (fallback / "server-side extraction") | Browser sends JPEG frames (≤15 fps, ≤640 px); server runs `HolisticLandmarker` on CPU | Frames go to localhost only |
| Upload | Server decodes with OpenCV, runs `HolisticLandmarker` at ≤30 fps, ≤960 px wide | Stays on the server, temp file deleted after the job |

Nothing but gloss strings and confidences is ever sent to an LLM.

## 1. Recognition pipeline (`backend/app/recognition/`)

```
LandmarkFrame ─► SigningGate ─► segment / pause / end events
                     │
                     ▼
              trailing buffer (12 s) ─► SignRecognizer.classify(window)
                                            ├─ HWGAT head      (2,002 words)   ┐ confidence-weighted
                                            ├─ INCLUDE head    (263 words)     ├─ alias fusion
                                            └─ SL-GCN head     (263 words)*    ┘
                                            ▼
                                    fused {label, p, margin, agreement}
                                            ▼
                               GlossEmitter: confident / uncertain "(?)" / UNKNOWN
                                            ▼
                     sentence buffer ─(rest ≥1.2 s or 12 glosses)─► SentenceBuilder
```
`*` every head is optional at runtime: a missing checkpoint disables that head only (see `docs/models.md`).

### SigningGate (`gate.py`)
No learned model. Per frame it computes **motion energy** = mean displacement of the tracked hand landmarks between consecutive frames, in shoulder-widths per second, median-filtered over 5 frames (the "optical flow from pose" feature of Moryossef et al. 2020, *Real-Time Sign Language Detection using Human Pose Estimation*). Hysteresis:

* IDLE → ACTIVE when a hand is visible and energy > 0.9 for 3 frames (`segment_start`).
* ACTIVE → IDLE when energy < 0.35 for 15 frames or no hand is visible for 12 frames (`segment_end`).
* Inside a segment, a hold of 8 frames below 0.4 that is ≥1 s after the last boundary emits a `pause` (a candidate sign boundary in continuous signing).

### SignRecognizer (`recognizer.py`)
* **Live feedback:** while ACTIVE, every 400 ms (1.2 s on CPU) the current sub-segment (plus 120 ms lead/lag) is classified and shown in the UI as the "latest window". These windows never emit glosses.
* **Emission:** on `pause` or `segment_end` the sub-segment is classified once more and a gloss is emitted. Segments shorter than 0.5 s are ignored (hand flicks). Segments longer than 4.5 s without a pause are cut.
* **Fragment merge:** a hold in the middle of a sign looks like a pause. At `segment_end`, if the segment produced ≥2 fragments that were not all confident, the *whole* segment is classified again; if that is confident and better than every fragment, the fragments are replaced by the single gloss.
* **Fusion:** each head's prior weight (HWGAT 0.6, SL-GCN 0.25, INCLUDE 0.15) is scaled by that head's own top-1 probability and renormalised over the heads that answered, so an unsure head cannot drown out a sure one and disagreement between sure heads lowers the fused confidence. INCLUDE-family labels are mapped to HWGAT labels by normalised aliases (`vocab.py`, e.g. `television` ↔ `Television/T.V.`, `thankyou` ↔ `Thank You`; 223 of 263 map). `agreement` is true when at least two heads give ≥0.1 to the fused label. The per-head probabilities and the weights used are part of every window result. A head that throws is skipped for that window and logged.
* **Decision:** `p ≥ 0.55 and margin ≥ 0.15` → confident; `0.35 ≤ p < 0.55` → uncertain (rendered `word(?)`); `p < 0.35` → `UNKNOWN`. Thresholds are in `.env` and adjustable live from the UI.
* **Debounce:** the same label emitted again within 350 ms of the previous one is merged (one sign split by a micro-hold); genuine repetitions (HELP HELP) are kept.
* **Sentence boundary:** IDLE for ≥1.2 s after at least one gloss, 12 glosses, or the "End sentence now" control.

### Language layer (`backend/app/language/`)
1. `joiner.py` – deterministic ISL-grammar joiner, always runs first and is displayed immediately: SOV → SVO when a verb ends the sequence, copula insertion between a pronoun and a predicate, sentence-final WH sign fronted with "?", NOT placed after the verb, time words first, greetings handled, `UNKNOWN` → `[unknown sign]`, uncertain → `word(?)`.
2. `llm.py` – optional polish (`anthropic` via the official SDK with a JSON-schema `output_config`, or a local `ollama` model). Input is only the gloss list with confidences. The system prompt forbids adding content words and requires `[unknown sign]` to be preserved.
3. `verifier.py` – every content word of the LLM sentence must lemmatise to an input gloss (or be an allow-listed function word); every non-unknown gloss must appear; the number of `[unknown sign]` markers must equal the number of `UNKNOWN` glosses. If any check fails the joiner text stays final and the UI shows the rejection reason.

## 2. Safety pipeline (`backend/app/safety/`)

```
LandmarkFrame ─► PostureAnalyzer (per frame)  ─┐
              ─► GestureFSM (per frame)        ├─► SafetyMonitor fusion ─► status, signals, reasons, events
              ─► ActionHead every 500 ms       │
recognised glosses in the safety lexicon ──────┘
```

* **PostureAnalyzer** (`posture.py`): MediaPipe pose → COCO-17; torso angle (shoulder-mid → hip-mid vs vertical; shoulder-line roll when hips are not visible), visible-joint bounding-box ratio, mean joint speed and hip vertical velocity in torso-lengths/s (EMA 0.3), head drop over the last second, keypoint quality. Flags: `upright` (<30°), `lying` (>60° and wide box), `sudden_drop` (hip velocity >1.4 tl/s or head drop >0.6 tl, after a 10-frame warm-up), `frantic` (speed >2.2 tl/s for ≥1.5 s), `immobile_s` (speed <0.06 tl/s).
* **ActionHead** (`models/stgcnpp.py`): pyskl ST-GCN++ (NTU RGB+D 60) on the last 100 frames, every 500 ms, **only if ≥80 % of frames have ≥70 % of joints visible** (the model is unreliable on partial bodies and scores random noise as "falling"). Probabilities for falling, staggering, medical classes (cough, headache, chest/back/neck pain, nausea) and hand waving are averaged over the last 5 runs.
* **GestureFSM** (`gesture.py`): Signal-for-Help = OPEN_PALM → THUMB_TUCKED → FIST on one visible hand (any height), each pose held ≥3 frames, whole cycle within 3 s; cycles counted over 8 s. Hand poses are computed in pixel space: a finger is extended when its tip is ≥5% farther from the wrist than its PIP joint (real hands: 1.23–1.43 extended, 0.56–0.76 curled); the thumb is tucked when its tip, projected on the index-knuckle → pinky-knuckle axis, lies ≥0.1 of the way across the palm (real open palms score −0.8 to −1.1, folded thumbs +0.19 to +0.55). The UI shows each hand's live pose and the sequence stage so you can see what the detector sees. Help-waving = raised wrist oscillating sideways (≥3 direction changes in 2 s, amplitude >0.3 shoulder-widths).
* **Safety lexicon** (`monitor.py`): confident glosses such as Help, Dangerous, Police, Pain, Hurt, Ambulance, Fire, Attack, Sick, Accident, Urgent count as evidence for 20 s.
* **Fusion state machine** (`monitor.py`):
  * fall track: NORMAL → SUSPECT on sudden drop or ST-GCN++ falling >0.6 → FALLEN when lying holds ≥1.5 s (SUSPECT clears after 5 s otherwise) → RECOVERING after 5 s upright → NORMAL.
  * long lie: lying + immobile ≥60 s.
  * distress: 1 Signal-for-Help cycle or a HELP sign → WARNING; 2 cycles, or a cycle plus a HELP sign/waving, or two HELP signs → CRITICAL (30 s cooldown).
  * abnormal motion: frantic ≥1.5 s or staggering >0.5. Medical cue: sustained ≥4 s (hand-to-face signs are brief).
  * status: CRITICAL = fallen + (immobile ≥10 s or medical or distress), long lie, or critical distress; WARNING = fallen, distress warning, lying + immobile, abnormal + medical; WATCH = suspect fall, immobility, abnormal motion, waving, lying, recent safety sign; else NORMAL.
  * Every signal carries a value (probability or seconds) and a reason string; `reasons` lists the evidence lines shown in the UI (e.g. "Fall detected — 91 %", "Prolonged immobility — 12 s", "HELP sign recognised — 94 %"). Events are logged with a 30 s per-key cooldown; when the person leaves the frame timers freeze instead of clearing.

## 3. Transport
`WS /ws/stream` carries client landmarks/frames/controls and server `update` snapshots (≤10 Hz, plus one immediately after every final window). `POST /api/analyze` runs the same pipeline on a file in a worker thread and returns the whole timeline for scrubbing. Full message shapes: `docs/api-contract.md`.
