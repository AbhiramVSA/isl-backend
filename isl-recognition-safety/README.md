# ISL pipeline inspector — Indian Sign Language recognition + safety monitor

A local web application that watches a webcam or an uploaded video, recognises isolated Indian Sign Language (ISL) signs from continuous signing with **pretrained models only**, turns the recognised gloss sequence into an English sentence **without inventing anything for unrecognised signs**, and in parallel flags observable safety events (falls, lying still, distress gestures, help/danger signs) with the evidence behind every alert.

Everything the pipeline sees and decides is exposed in the UI: landmarks found per frame, the signing gate, each model head's top-5 with confidences, the raw gloss sequence with `UNKNOWN` and `word(?)` markers, the deterministic sentence, the optional LLM sentence and whether it passed grounding verification, and the safety signals with their reasons.

> This is a research demonstration. ISL recognition from a webcam is far from solved, and the safety monitor detects *visible events*, not intent or mental state. See [Known limitations](#known-limitations).

## What runs inside

| Role | Model | Vocabulary / classes | License | Why (see `docs/models.md`) |
|---|---|---|---|---|
| Landmarks (browser and server) | MediaPipe HolisticLandmarker 1.0.1 | 33 pose + 21+21 hand + 478 face points | Apache-2.0 | Fastest CPU option (≈30 ms/frame), the layout modern ISL models were trained on, runs in the browser so raw video need not leave the client |
| ISL words, primary | **HWGAT** (RKMVERI) trained on FDMSE-ISL | **2,002 ISL words** | MIT | Only ISL model with a signer-independent evaluation (93.9% top-1, 20 Deaf signers); pure PyTorch; 20 M params |
| ISL words, second opinion | **INCLUDE keypoint Transformer** (AI4Bharat / IIT Madras) | 263 ISL words | MIT | Independent corpus and signers; reimplemented in plain PyTorch and verified bit-exact against the reference |
| ISL words, third opinion | **OpenHands SL-GCN** (AI4Bharat) | 263 ISL words | Apache-2.0 | 93.5% on INCLUDE test; ported to plain PyTorch, verified exact against the reference |
| Action / fall event | **ST-GCN++** (pyskl) trained on NTU RGB+D 60 | 60 actions incl. falling, staggering, medical cues | Apache-2.0 (dataset research-only) | Only pretrained model that separates falling/staggering from sitting/picking up; ported to plain PyTorch |
| Posture, immobility, gestures | Geometric rules and finite-state machines on landmarks | — | — | Explainable; no public weights exist for Signal-for-Help |
| Gloss → sentence | Deterministic ISL-grammar joiner, optional Claude (`claude-opus-5`) or local Ollama polish with a grounding verifier | — | — | The LLM only ever sees gloss strings + confidences, and its output is rejected if any content word is not grounded |

Nothing is fabricated: if a checkpoint is missing the head is disabled and reported; if no model is confident the gloss is `UNKNOWN`; if the LLM invents a word the deterministic sentence is used and the rejection reason is shown.

## Requirements

* Windows 11 / Linux / macOS with Python **3.11 or 3.12** (tested on 3.12.4, Windows 11)
* Node 20+ (frontend build)
* Optional NVIDIA GPU (tested on an RTX 3060 Laptop 6 GB, CUDA 12.6 wheels). CPU works; the word heads then run at a lower cadence (`ISL_WINDOW_STRIDE_CPU_MS`).
* ≈600 MB of model files (downloaded by `scripts/download_models.py`)
* A webcam for the live mode; `ffmpeg` is not required (OpenCV decodes uploads)

Measured on this laptop: MediaPipe Holistic ≈30 ms/frame CPU; HWGAT 43 ms/clip GPU fp32, 21 ms fp16, ≈800 ms CPU; INCLUDE transformer 5 ms GPU; ST-GCN++ 63 ms/clip CPU. Uploaded 1080p clips process at ≈15–20 fps on GPU, ≈12 fps CPU.

## Install

```bash
git clone <this repo> isl && cd isl
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cu126   # GPU; or plain `pip install torch` for CPU
pip install -r requirements.txt
python scripts/download_models.py          # MediaPipe task, HWGAT (Google Drive via gdown), INCLUDE (wandb), ST-GCN++ (openmmlab)

cd frontend && npm install && npm run build && cd ..   # also copies the MediaPipe WASM + model into frontend/public
```

`download_models.py` verifies byte sizes and tells you which head is disabled if a download fails; the app still starts.

## Docker (recommended for a GPU server, e.g. an A100 box)

Host requirements: Docker with the compose plugin, an NVIDIA driver (≥ 560 for the CUDA 12.6 wheels) and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Check with `docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu22.04 nvidia-smi`.

```bash
git clone https://github.com/AbhiramVSA/isl-recognition-safety.git && cd isl-recognition-safety
cp .env.example .env            # optional: set ISL_LLM_PROVIDER=anthropic and ANTHROPIC_API_KEY here
docker compose up -d --build    # builds the frontend + backend image (~6 GB, PyTorch CUDA wheels)
docker compose logs -f          # first start downloads ~600 MB of weights into ./models, then serves
curl http://localhost:8000/api/health
```

Notes:
* Weights live in the `./models` bind mount, so rebuilds do not re-download. If the Google Drive download of the HWGAT weights is throttled on your network, download `best_model_and_FDMSE_class_map.zip` from https://drive.google.com/file/d/11DbOxiPmABieflBxGuV28org5Pm3ROsu/view manually into `models/hwgat/` and restart.
* **Webcam from a remote server:** browsers only allow camera access on `localhost` or HTTPS. Tunnel the port so the page is served as localhost: `ssh -L 8000:localhost:8000 user@a100-host`, then open http://localhost:8000 on your laptop. Landmarks are computed in your browser and only landmark coordinates travel through the tunnel. Alternatively put the container behind an HTTPS reverse proxy (WebSocket pass-through required for `/ws/`).
* Video uploads and the API work over plain HTTP from anywhere.
* CPU-only host: `TORCH_INDEX=https://download.pytorch.org/whl/cpu docker compose up -d --build`.
* Change the host port with `ISL_PORT=9000 docker compose up -d`.

## Run without Docker

```bash
# from the repo root, venv active
cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Open http://127.0.0.1:8000 — the backend serves the built frontend. `GET /api/health` shows which models loaded, the device, and the LLM provider status.

Development with hot reload for the UI: `cd frontend && npm run dev` (Vite proxies `/api` and `/ws` to port 8000).

Webcam access requires `http://localhost` / `127.0.0.1` or HTTPS.

## Configure

Copy `.env.example` to `.env`. All settings have defaults (`backend/app/config.py`). The important ones:

| Variable | Meaning |
|---|---|
| `ISL_DEVICE` | `auto` (default), `cuda` or `cpu` |
| `ISL_LLM_PROVIDER` | `none` (default, deterministic sentences only), `anthropic`, or `ollama` |
| `ANTHROPIC_API_KEY` | read by the official Anthropic SDK when the provider is `anthropic` (model `ISL_ANTHROPIC_MODEL`, default `claude-opus-5`). Only gloss text is sent. |
| `ISL_OLLAMA_MODEL` / `ISL_OLLAMA_URL` | local model for offline polishing (e.g. `qwen2.5:3b`) |
| `ISL_CONF_HIGH` / `ISL_CONF_LOW` / `ISL_MARGIN_MIN` | confident / uncertain / unknown thresholds (also adjustable live in the UI settings drawer) |
| `ISL_SENTENCE_REST_MS` | rest time that closes a sentence (default 1200 ms) |
| `ISL_IMMOBILE_WARN_S`, `ISL_LONG_LIE_S`, `ISL_EVENT_COOLDOWN_S` | safety timers |
| `ISL_ENABLE_HWGAT` / `ISL_ENABLE_INCLUDE` / `ISL_ENABLE_STGCNPP` | disable a head |

## Using the app

1. **Webcam** — press *Start camera*. Landmarks are computed in the browser (WebGL) and streamed to the server; the video itself never leaves the page. If the browser landmarker cannot initialise, or you toggle *Server-side extraction*, JPEG frames are sent to localhost instead.
2. Sign one sign at a time with a short rest between signs, facing the camera with your upper body and both hands in frame. The gate opens when your hands move, the *Latest window* panel shows live head predictions, and a gloss is emitted when you pause or drop your hands.
3. Rest for ~1.2 s (or press *End sentence now*) to close a sentence. The deterministic sentence appears immediately; with an LLM provider configured the polished version replaces it only if verification passes.
4. **Upload video** — pick a file; the server runs the same pipeline and returns a scrubbable timeline with landmarks, glosses, sentences and safety state at every moment.
5. **Safety panel** — status NORMAL / WATCH / WARNING / CRITICAL, the signals behind it (probabilities, seconds), the exact evidence lines, and an event log.
6. **Models & limitations** — every model's dataset, license, reported accuracy, vocabulary (searchable) and limitations, straight from `GET /api/models`.

## Tests

```bash
cd backend && python -m pytest -q          # 43 tests: preprocessing, joiner, verifier, LLM fallback, gate, recognizer fusion, safety fusion, strict checkpoint loading
python scripts/safety_trace.py some_video.mp4        # prints the safety monitor's decisions over time
python scripts/eval_clips.py <dir with word folders>  # streams isolated-sign clips through the pipeline and scores the emitted glosses
```

Validation on real data is recorded in `docs/evaluation.md`.

## Repository layout

```
backend/app/
  config.py            settings (.env)
  landmarks/           LandmarkFrame + server-side HolisticLandmarker
  models/              hwgat.py, include_transformer.py, include_features.py, slgcn.py, stgcnpp.py, registry.py
  recognition/         gate.py (signing gate), recognizer.py (windows, fusion, emission), vocab.py (label aliases)
  language/            joiner.py, llm.py, verifier.py, builder.py
  safety/              posture.py, gesture.py, monitor.py (fusion state machine)
  pipeline.py          SessionPipeline shared by webcam and upload paths
  api/                 stream.py (WebSocket), analyze.py (uploads), state.py; main.py (FastAPI app)
backend/tests/         pytest suite
frontend/              Vite + React + TypeScript UI (MediaPipe in the browser)
scripts/               download_models.py, safety_trace.py
docs/                  models.md, pipeline.md, evaluation.md, api-contract.md, research/ (model surveys), superpowers/specs/ (design)
models/                downloaded checkpoints (git-ignored)
```

## Privacy

* Webcam frames stay in the browser by default; only landmark coordinates are sent to the local server.
* Uploaded videos are written to a temp file, processed, and deleted.
* The LLM (if enabled) receives only gloss strings with confidences, never frames or landmarks.
* Nothing is stored between sessions.

## Known limitations

* **Vocabulary ≠ fluency.** HWGAT recognises 2,002 isolated citation-form signs from the FDMSE dictionary. Continuous, coarticulated signing, regional variants, classifier constructions and fingerspelling are outside its training data. On INCLUDE clips (different corpus and signers) it reached 8/18 top-1 in our test, with well-separated confidences (0.7–0.99 when right, ≤0.3 when wrong), which is what makes the `UNKNOWN` mechanism work.
* **The INCLUDE head is signer-dependent** (7 signers, split by video) and expects a full-upper-body framing; it is a second opinion, weighted by its own confidence.
* **Segmentation is heuristic.** Signs are segmented by hand motion energy and pauses; fluent signing without pauses is cut every 4.5 s and may straddle signs.
* **No fingerspelling** in this version: every public ISL alphabet model is a still-image classifier trained on studio photos with no evidence of webcam transfer, so shipping one would be pretending.
* **Safety detection is rule + skeleton based.** ST-GCN++ was trained on lab data with HRNet keypoints; with MediaPipe keypoints and a webcam it confuses normal walking with "staggering" and scores random noise as "falling", so it is only corroborating evidence gated on keypoint quality. MediaPipe often loses the pose of a person lying on the floor; the monitor therefore treats "person untracked right after a sudden drop" as fall evidence and escalates when nobody stands up. Falls need the torso in view; a desk webcam showing only the head and shoulders cannot detect them reliably.
* **The Signal-for-Help detector is geometric** (open palm → thumb tucked → fist) and was validated on synthetic hands and the author's own webcam only.
* **Not a medical or emergency system.** Alerts are hints for a human, with the evidence shown.

## License and attributions

Application code: MIT. Bundled/downloaded third-party components keep their own licenses: MediaPipe (Apache-2.0), HWGAT code and weights (MIT, Patra et al. 2025), INCLUDE code and weights (MIT, AI4Bharat; dataset CC BY 4.0), OpenHands (Apache-2.0), pyskl ST-GCN++ (Apache-2.0; NTU RGB+D dataset terms are research-only). See `docs/models.md` for citations.
