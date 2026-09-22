# ISL pipeline inspector (frontend)

React + Vite + TypeScript client for the ISL recognition and safety-monitoring backend. It implements the protocol in `../docs/api-contract.md` and shows every intermediate the server reports: landmark presence, gate state, per-head window scores, the raw gloss stream, sentences, and the safety state. Nothing shown is computed or simulated in the browser except the landmark overlay.

## Run

```
npm install        # also copies MediaPipe WASM + the holistic model into public/
npm run dev        # http://localhost:5173, proxies /api and /ws to http://localhost:8000
npm run build      # tsc + vite build into dist/ (backend serves dist/ in production)
npm run preview    # serve dist/ on http://localhost:4173
```

The backend must be listening on `http://localhost:8000` for anything to appear; without it the header shows `connecting…` / `reconnecting` and every panel shows its empty state.

## Assets copied at install

`scripts/copy-wasm.mjs` runs on `postinstall` and `prebuild` (idempotent, Windows-safe):

- `node_modules/@mediapipe/tasks-vision/wasm/*` -> `public/mediapipe-wasm/`
- `../models/mediapipe/holistic_landmarker.task` -> `public/models/holistic_landmarker.task` (skipped silently if missing)

Both destinations are git-ignored. If the model is absent, the in-browser landmarker fails to initialise and the webcam path falls back to sending JPEG frames to the server.

## Sources

- Webcam: `HolisticLandmarker` runs in the browser (GPU delegate, CPU fallback) and only landmarks are sent over `/ws/stream` at up to 30 fps. Toggle "Server-side extraction" in Settings to send JPEG frames (up to 15 fps, 640 px wide, quality 0.7) instead.
- Upload: the file is posted to `/api/analyze`, the job is polled every 700 ms, and the returned timeline is replayed against the video with a scrubbable timeline; the panel contents follow `currentTime`.

## Layout

```
src/
  App.tsx              source switch, settings, health, wiring
  types.ts             message and object types mirroring the API contract
  api.ts               REST helpers
  landmarks.ts         MediaPipe result -> wire message, skeleton drawing
  format.ts            number formatting, nearest-by-time binary search
  hooks/useWebSocket   /ws/stream client with backoff and 50 ms update batching
  hooks/useLandmarker  HolisticLandmarker lifecycle (GPU -> CPU fallback)
  hooks/useWebcam      getUserMedia lifecycle
  components/          one file per panel
  styles.css           single stylesheet
```
