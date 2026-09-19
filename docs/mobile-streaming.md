# Equal app live streaming

Live ISL recognition for the Equal app: glosses arrive **while the user is
still signing**, instead of after a finished clip upload to
`POST /app/api/v1/predict`.

**Base address: `https://<host>/app`** — same mount as
[equal-app-api.md](equal-app-api.md).

## Which endpoint to use

| Socket | Phone sends | Use when |
| --- | --- | --- |
| `WS /app/api/v1/stream/landmarks` | MediaPipe landmarks JSON (~5 KB/frame) | **Preferred.** Phone runs MediaPipe Tasks on-device; lowest bandwidth and server CPU. |
| `WS /app/api/v1/stream/video` | Base64 JPEG frames, 640 px max, 5–10 fps | Fallback for phones without on-device MediaPipe. Server decodes (CPU-hot, tighter caps). |

No auth header on either socket — like `/predict`, recording starts before
anyone signs in. The `hello` frame hands you a `stream_id` + `draft_token`
instead; keep both until the report is filed.

## Session flow

```
open WS ──▶ hello ──▶ landmarks/frame… ──▶ update… ──▶ close ──▶ done
                                                              └─▶ GET draft ──▶ POST /app/api/v1/reports
```

1. Open the socket. First frame down is always:
   ```json
   {"type": "hello", "stream_id": "a1b2c3d4e5f6",
    "draft_token": "opaque-save-this", "kind": "landmarks"}
   ```
2. Send frames (below). Updates stream back at ≤ 10 Hz:
   ```json
   {"type": "update", "t_ms": 1234.0,
    "vision": {"pose": true, "fps_in": 12.0, "quality": 0.8},
    "gate": {"state": "ACTIVE"},
    "window": {"final": false},
    "glosses": [{"label": "HELP", "display": "help", "p": 0.9,
                 "t_start_ms": 1000, "t_end_ms": 1400}],
    "sentences": [{"id": "s1", "text": "need help", "glosses": []}],
    "safety": {"status": "ok"}, "safety_events": []}
   ```
   Render `glosses[-1]` as the live caption; append `sentences[].text` as it
   arrives. `window.final == true` frames are never throttled.
3. Close the socket (or hit a limit) → server saves the draft and, if you are
   still connected, sends:
   ```json
   {"type": "done", "stream_id": "a1b2c3d4e5f6", "transcript": "need help",
    "sentences": [], "frames_seen": 180, "duration_ms": 12000}
   ```
4. Fetch the draft and file the report:
   ```
   GET /app/api/v1/stream/{stream_id}/draft?token={draft_token}
   → {"stream_id", "kind", "transcript", "sentences", "safety_events",
       "frames_seen", "duration_ms", "completed", "expires_at"}
   ```
   then `POST /app/api/v1/reports` with `transcript` and `duration_ms` from
   the draft. Unknown id, wrong token, and expired drafts all answer `404`
   (indistinguishable, so ids cannot be probed). Drafts expire after
   `STREAM_DRAFT_TTL_HOURS` (24 h default).

## Sending frames

Landmarks socket — one JSON object per frame, ≤ 15 fps:
```json
{"type": "landmarks", "t_ms": 1234.0, "width": 640, "height": 480,
 "pose": [[0.5, 0.5, 0.0, 0.9]], "left_hand": [[0.5, 0.5, 0.0]],
 "right_hand": null, "face": true}
```
`pose` is 33×`[x, y, z, visibility]`, hands are 21×`[x, y, z]` in MediaPipe
normalised coordinates; all values finite. At least one of `pose`,
`left_hand`, `right_hand` must be present. `t_ms` is monotonic
milliseconds — the server uses it for sentence segmentation and
`duration_ms`.

Video socket — same, but frames:
```json
{"type": "frame", "t_ms": 1234.0, "jpeg": "<base64>"}
```

Control messages (both sockets):
```json
{"type": "control", "action": "reset"}
{"type": "control", "action": "end_sentence"}
{"type": "control", "action": "config", "llm_enabled": true, "min_confidence": 0.5}
```
`reset` also clears the server-side draft accumulator.

Bad frames never kill the stream — you get
`{"type": "error", "message": "bad message: …"}` and continue. Wrong-kind
frames (landmarks on `/video`) are rejected the same way.

## Fallback and close codes

* `4403` + `{"type":"error","message":"Live recognition is unavailable…",
  "fallback":"/app/api/v1/predict"}` — recogniser down. Record a short clip
  and `POST /app/api/v1/predict` instead.
* `4409` — server full (per-IP or per-kind cap). Back off and retry; honour
  any `Retry-After`.
* `1000` — normal end (you closed, or a budget below ran out).

## Budgets (defaults; `STREAM_*` env overrides)

| Budget | Landmarks | Video |
| --- | --- | --- |
| Concurrent streams (global) | 50 | 10 |
| Per IP | 2 | 2 (shared) |
| Inbound rate | 15 fps (over-rate frames dropped) | 10 fps |
| Max message | 256 KB | 512 KB |
| Max duration / bytes per stream | 10 min / 200 MB | same |

`ISL_WS_URL` (default `ws://isl:8000/ws/stream`) points the bridge at the
recognition service; `ISL_STREAM_CONNECT_TIMEOUT_SECONDS` is 8 s.

## Android snippets

```kotlin
// Landmarks path: MediaPipe Tasks HolisticLandmarker on-device.
val msg = JSONObject()
    .put("type", "landmarks")
    .put("t_ms", clock.uptimeMillis().toDouble())
    .put("width", 640).put("height", 480)
    .put("pose", JSONArray(poseFloats))          // 33 x [x,y,z,vis]
    .put("left_hand", leftJsonOrNull)            // 21 x [x,y,z] | null
    .put("right_hand", rightJsonOrNull)
    .put("face", facePresent)
ws.send(msg.toString())   // ≤ 15 fps; drop, never queue

// Video path: CameraX → 640 px → JPEG q70 → base64, 5–10 fps.
val out = ByteArrayOutputStream()
bitmap.compress(Bitmap.CompressFormat.JPEG, 70, out)
ws.send(JSONObject()
    .put("type", "frame")
    .put("t_ms", nowMs())
    .put("jpeg", Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP))
    .toString())
```

Reading:
```kotlin
when (json.getString("type")) {
    "hello" -> { streamId = json.getString("stream_id"); draftToken = json.getString("draft_token") }
    "update" -> renderLive(json)   // glosses.last() + sentences
    "done" -> onStreamEnd(json.optString("transcript"))
    "error" -> if (json.optString("fallback").isNotEmpty()) fallBackToClipUpload()
}
// After close:
api.getDraft(streamId, draftToken)   // → transcript for the report POST
```

## Testing checklist

* Happy path on each socket: hello → frames → updates → done → draft
  `completed: true` with the spoken transcript.
* Bad frame (garbage base64, 32-row pose, `NaN`) → `error`, stream survives.
* Landmarks frame on `/video` → `error`, then a real frame still decodes.
* Recogniser stopped → `4403` + fallback hint; clip upload still works.
* Draft fetch with wrong token → `404`; expired draft → `404`.
* Two streams from one IP + a third → `4409` on the third.
