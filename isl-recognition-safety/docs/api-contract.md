# API contract (backend ⇄ frontend)

Backend: FastAPI on `http://localhost:8000`. In development the Vite dev server proxies `/api` and `/ws` to it. In production the backend serves the built frontend from `frontend/dist` at `/`.

## REST

### `GET /api/health`
```json
{
  "status": "ok",
  "device": "cuda" | "cpu",
  "torch": "2.14.0+cu126",
  "mediapipe": "1.0.1",
  "models": {
    "hwgat":   {"loaded": true, "error": null, "vocab_size": 2002, "license": "MIT", "name": "HWGAT (FDMSE-ISL)"},
    "include": {"loaded": true, "error": null, "vocab_size": 263, "license": "MIT", "name": "INCLUDE transformer (AI4Bharat)"},
    "stgcnpp": {"loaded": true, "error": null, "vocab_size": 60, "license": "Apache-2.0", "name": "ST-GCN++ NTU-60 (pyskl)"},
    "holistic": {"loaded": true, "error": null, "name": "MediaPipe HolisticLandmarker"}
  },
  "llm": {"provider": "anthropic" | "ollama" | "none", "available": true, "model": "claude-opus-5", "error": null}
}
```

### `GET /api/models`
Returns model cards: `{ "hwgat": {"name","vocab": [...2002 words], "dataset","license","reported_accuracy","limitations"}, "include": {...}, "stgcnpp": {...}, "safety_lexicon": {"HELP": ["Help [VEB]"], ...} }`

### `POST /api/analyze` (multipart, field `file`)
Runs the whole pipeline on an uploaded video server-side (landmarks extracted on the server). Returns `202 {"job_id": "..."}`.

### `GET /api/analyze/{job_id}`
```json
{
  "job_id": "...", "state": "queued" | "running" | "done" | "error", "progress": 0.0-1.0, "error": null,
  "result": {                       // present when done
    "duration_s": 3.4, "fps": 25.0, "frames": 85, "width": 1920, "height": 1080,
    "timeline": [ <Update snapshot at each emitted change> ],
    "glosses": [ <Gloss> ],
    "sentences": [ <Sentence> ],
    "safety": <SafetyState>,
    "safety_events": [ <SafetyEvent> ],
    "landmark_frames": [ {"t_ms": 0, "pose": [[x,y,z,vis]...33] | null, "left_hand": [[x,y,z]...21] | null, "right_hand": ... } ]  // for overlay playback; optional, may be downsampled
  }
}
```

## WebSocket `WS /ws/stream`

### Client → server messages
```jsonc
// Landmarks extracted in the browser (preferred; raw video never leaves the browser)
{"type": "landmarks", "t_ms": 12345, "width": 640, "height": 480,
 "pose": [[x,y,z,visibility] × 33] | null,        // normalised 0..1 image coords (x,y), z relative, visibility 0..1
 "left_hand": [[x,y,z] × 21] | null,             // MediaPipe "left" = the person's left hand
 "right_hand": [[x,y,z] × 21] | null}

// Fallback: raw JPEG frame; server runs HolisticLandmarker (slower, video leaves browser to localhost only)
{"type": "frame", "t_ms": 12345, "jpeg": "<base64>"}

// Controls
{"type": "control", "action": "reset"}          // clear buffers, glosses, sentences, safety state
{"type": "control", "action": "end_sentence"}   // force sentence boundary now
{"type": "control", "action": "config", "llm_enabled": true, "min_confidence": 0.55}
```

### Server → client messages
```jsonc
{"type": "hello", "session_id": "...", "device": "cuda", "models": {...same as health.models...}, "llm": {...}}

{"type": "update", "t_ms": 12345,
 "vision": {"pose": true, "left_hand": false, "right_hand": true, "face": true,
            "fps_in": 28.5, "quality": 0.91},                // what the vision model saw this frame
 "gate": {"state": "ACTIVE" | "IDLE", "energy": 0.42, "segment_ms": 830, "rest_ms": 0},
 "window": {                                                 // latest classified window (may be null)
   "t_start_ms": 11000, "t_end_ms": 12345, "frames": 34,
   "heads": {
     "hwgat":   {"top": [{"label": "Water", "p": 0.81}, ... 5], "latency_ms": 22},
     "include": {"top": [{"label": "water", "p": 0.40}, ... 5], "latency_ms": 5}
   },
   "fused": {"label": "Water", "p": 0.84, "margin": 0.6, "agreement": true}
 },
 "glosses": [ <Gloss> ],                                     // current sentence buffer (raw recognised sequence)
 "sentences": [ <Sentence> ],                                // completed sentences (most recent last)
 "safety": <SafetyState>,
 "safety_events": [ <SafetyEvent> ]                          // rolling log, most recent last (max 50)
}

{"type": "error", "message": "..."}
```

### Shared objects
```jsonc
Gloss = {"id": 17, "label": "WATER" | "UNKNOWN", "display": "Water", "p": 0.84, "status": "confident" | "uncertain" | "unknown",
         "t_start_ms": 11000, "t_end_ms": 12345, "heads": {"hwgat": 0.81, "include": 0.40}, "safety_lexicon": null | "HELP"}

Sentence = {"id": 3, "glosses": [Gloss...], "joiner_text": "I want water.", "llm_text": "I want some water." | null,
            "final_text": "I want some water.", "source": "llm" | "joiner",
            "verification": {"passed": true, "reason": null} | {"passed": false, "reason": "content word 'please' not grounded"},
            "llm_error": null, "t_start_ms": 9000, "t_end_ms": 12345}

SafetyState = {"status": "NORMAL" | "WATCH" | "WARNING" | "CRITICAL", "score": 0.0-1.0,
  "signals": [ {"key": "fall", "label": "Fall detected", "value": 0.91, "unit": "p" | "s", "active": true, "reason": "ST-GCN++ falling p=0.91 (5-vote), hip drop 2.1 torso-lengths/s"} ... ],
  "tracks": {"fall": "NORMAL" | "SUSPECT" | "FALLEN" | "RECOVERING", "long_lie": bool, "distress": "NONE"|"WARNING"|"CRITICAL", "abnormal_motion": bool},
  "posture": {"lying": false, "upright": true, "torso_angle_deg": 12.0, "speed": 0.3, "immobile_s": 0.0, "person_present": true},
  "action": {"top": [{"label": "falling", "p": 0.91}, ...], "valid": true},
  "gesture": {"state": "OPEN_PALM" | "THUMB_TUCKED" | "FIST" | "NONE", "cycles": 0, "waving": false},
  "reasons": ["Fall detected — 91%", "Prolonged immobility — 12 s", "HELP sign recognised — 94%"]}

SafetyEvent = {"id": 5, "t_ms": 12345, "severity": "WATCH"|"WARNING"|"CRITICAL", "key": "fall", "title": "Fall detected", "evidence": ["..."], "cleared_t_ms": null}
```

Update cadence: ≤ 10 Hz. `window` and `safety.action` change every ~0.4–0.5 s; the rest per frame.
