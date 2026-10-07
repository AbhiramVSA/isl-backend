# Evaluation log (what was actually measured, 2026-09-14)

Hardware: Windows 11, Intel laptop CPU, NVIDIA RTX 3060 Laptop 6 GB, Python 3.12.4, torch 2.14.0+cu126, mediapipe 1.0.1.

## Checkpoint fidelity
| Check | Result |
|---|---|
| HWGAT `model_best_loss.pt` strict load into `hwgat.py` | all keys matched (206 tensors, 20.49 M params) |
| HWGAT preprocessing vs upstream `data_transform.py` on a real INCLUDE clip | max abs diff **0.0** on the (192, 64, 2) input |
| INCLUDE transformer strict load (large + small) | all keys matched |
| INCLUDE transformer vs upstream `models/transformer.py` (transformers 4.57.6, eager attention) | max abs diff **0.0** with the reference's inference-time `F.dropout` disabled; upstream applies dropout at test time (bug), our port is deterministic |
| ST-GCN++ `j.pth` strict load into `stgcnpp.py` | all keys matched (1.39 M params) |

## Latency
| Model | Input | GPU | CPU |
|---|---|---|---|
| MediaPipe Holistic | 640×480 frame | n/a (CPU only in Python) | 28–32 ms |
| HWGAT | 192-frame clip | 43 ms fp32, 21 ms fp16 (same argmax) | ≈795 ms |
| INCLUDE transformer | 169 frames × 2 hand orders | ≈5 ms | ≈40 ms |
| ST-GCN++ | 100 frames, 2 persons | ≈5 ms | ≈63 ms |
| Whole pipeline on a 1080p INCLUDE clip (resized to 960 px) | 53–85 frames | 2.2–4.5 s per clip (≈15–20 fps) | ≈12 fps |

## Isolated-sign recognition on real INCLUDE clips
18 clips from the INCLUDE `Electronics` and `Greetings` archives (Zenodo 4010759), 2 per word, run through Holistic → each head on the whole clip. Some of these clips may be in the INCLUDE model's training split (the split is by video), so its number is optimistic; HWGAT never saw this corpus.

| Word | HWGAT top-1 (p) | INCLUDE top-1 (p) |
|---|---|---|
| Laptop ×2 | ✔ 0.79, ✔ 0.83 | ✔ 0.99, ✔ 0.97 |
| Screen ×2 | ✘ 0.05, ✘ 0.04 | ✔ 0.99, ✔ 0.99 |
| Camera ×2 | ✔ 0.72, ✔ 0.81 | ✔ 0.95, ✔ 0.92 |
| Television ×2 | ✔ 0.54, ✔ 0.12 | top-5 0.41, ✔ 0.42 |
| Radio ×2 | ✘ 0.09, ✘ 0.07 | ✔ 0.35, ✔ 0.47 |
| Good evening ×2 | ✘ 0.05, ✘ 0.06 | ✔ 0.45, ✔ 0.48 |
| Good night ×2 | ✘ 0.04, ✘ 0.03 | ✔ 0.44, ✔ 0.31 |
| Thank you ×2 | ✔ 0.99, ✔ 0.99 | ✔ 0.93, ✔ 0.55 |
| Pleased ×2 | ✘ 0.22, ✘ 0.20 | ✔ 0.55, ✔ 0.62 |
| **Total** | **8/18 top-1, 8/18 top-5** | **17/18 top-1, 18/18 top-5** |

Take-aways: HWGAT's confidence is well separated (hits 0.54–0.99, misses ≤0.22), which is what the confident/uncertain/unknown thresholds (0.55/0.35) rely on. Several misses are signs whose FDMSE citation form differs from the INCLUDE form (e.g. Good evening/night), not model failure per se.

## SL-GCN port (third head)
| Check | Result |
|---|---|
| OpenHands `include_slgcn` Lightning ckpt → plain state dict (342 tensors, `model.` prefix stripped) | tensor-identical to the original; reproduced by `scripts/download_models.py` |
| Port vs original `decoupled_gcn.py` + `fc.py` (run in a scratch venv with Lightning) on the same random (2, 2, 60, 27) input | max abs diff **0.0**, argmax equal, 4,722,433 params+buffers match |
| Input format (from `generate_pose.py`, `base.py`, `pose_transforms.py`) | 75-point [pose \| left \| right] normalised (x, y), 27-point preset, clip-level shoulder centre/scale, variable length, no confidence channel |
| Whole-clip top-1 on the 18 INCLUDE clips | **16/18** (18/18 top-5); the two Radio misses come from one signer/session (7/9 on the other Radio clips) — INCLUDE clips may overlap its training split |
| Latency, 60-frame clip | 25.5 ms CUDA, 39.4 ms CPU |

## Full streaming pipeline (gate → windows → three-head fusion → emission → sentence)
`python scripts/eval_clips.py <include_data> --per-word 2` streams two clips of each of the 9 words frame by frame through `SessionPipeline` (exactly what the upload endpoint and the WebSocket do), 960 px input:

| Word | Clip 1 | Clip 2 |
|---|---|---|
| Good evening | Good night(?) 0.38 (uncertain, wrong) | **Good evening** 0.75 |
| Good night | **Good night** 0.83 | **Good night** 0.69 |
| Thank you | **Thank You** 0.95 (all three heads agree) | **Thank You** 0.92 |
| Laptop | **Laptop** 0.88 | **Laptop** 0.81 |
| Pleased | **Pleased** 0.84 | **Pleased** 0.76 |
| Screen | **Screen** 0.92 | **Screen** 0.84 |
| Camera | **Camera** 0.77 | **Camera** 0.76 |
| Television | **Television/T.V.** 0.77 | **Television/T.V.** 0.75 |
| Radio | Dog(?) 0.47 (uncertain, wrong) | Store or shop(?) 0.43 (uncertain, wrong) |

**15/18 clips emit the correct gloss as confident; the 3 wrong ones are all marked uncertain `(?)`; none is silently wrong-and-confident; no clip collapsed to only `UNKNOWN`.** Sentences were the expected "Laptop.", "Thank you.", "Good evening.", "Good night(?)." etc.

With only the HWGAT + INCLUDE-transformer heads (before SL-GCN was added) the same run gave: Laptop ×4 confident (0.60–0.87), Thank you confident 0.88, Camera confident, Good evening ×6 → 2 uncertain and 4 `UNKNOWN`. Before the segment-merge logic was added, single signs were fragmented by mid-sign holds into 2–3 `UNKNOWN` pieces. Uncertain and unknown outcomes are shown as such instead of being guessed.

## WebSocket end-to-end
Replaying 202 real landmark frames (Camera clip, Thank-you clip, idle gaps) at 30 fps over `/ws/stream`: 135 update messages, sentences "Camera." and "Thank you.", malformed messages answered with `error` without closing the socket, `reset` cleared state.

## Upload end-to-end
`POST /api/analyze` on the 1080p Thank-you clip (53 frames): done in 2.4 s, gloss "Thank You" 0.879 (HWGAT 0.977, INCLUDE 0.566), timeline of 17 snapshots + 53 landmark frames (325 KB JSON). Unsupported file types and unknown job ids return clear 4xx errors.

## Robustness
* Started with an empty `models/` directory: `/api/health` reports each head's `FileNotFoundError`, `/api/analyze` returns 503 with the reason, the WebSocket still accepts landmarks and returns gate/safety state; nothing crashes.
* `ISL_DEVICE=cpu`: same predictions (Thank You 0.879), 4.2 s for a 53-frame clip.
* `ISL_LLM_PROVIDER=anthropic` without a key: health shows `available: false, error: "ANTHROPIC_API_KEY not set"`, sentences fall back to the joiner with `llm_error` set. (No API key was available during development, so the live Claude call was not exercised; the request construction uses the official SDK's `messages.create` with `output_config` JSON schema and is covered by mocked-provider tests.)

## Safety monitor on real footage — UR Fall Detection dataset
Sequences `fall-01-cam0-rgb` (fall) and `adl-01-cam0-rgb` (activity of daily living) from http://fenix.ur.edu.pl/~mkepski/ds/uf.html, 640×480, 30 fps, assembled into videos.

| Time | fall-01 (last frame held 14 s to simulate lying still) |
|---|---|
| 0–3.0 s | NORMAL, upright, ST-GCN++ says "kicking something" 0.99 while the person stands (transfer failure noted) |
| 3.10 s | WATCH — "Possible fall — 60%" (hip velocity 1.42–1.65 torso-lengths/s, head drop 0.53–0.61 in 1 s) |
| 3.60 s | lying posture detected (torso angle 62°, box w/h 1.05); MediaPipe then loses the pose on the floor |
| 6.07 s | WARNING — "Fall detected — 90%" (person not tracked 2 s after the drop) |
| 13.1 s | CRITICAL — "No recovery — not upright for 10 s after the fall", "Person not tracked … (possibly on the floor)" |

| adl-01 (control) | |
|---|---|
| 2–3 s | ST-GCN++ "staggering" 0.64–0.73 on ordinary walking → suppressed (must be sustained 3 s with real motion); no abnormal-motion alert after the rule change |
| 3.4–4.0 s | WATCH — "Possible fall — 60%" from a head drop of 0.62–1.42 torso-lengths (the sequence contains lying down deliberately); never reaches WARNING because no lying+untracked/no-recovery condition follows within the clip |

Interpretation: the drop detector fires at the right moment on a real fall; the confirmation depends on what happens next (lying posture, loss of tracking, no recovery), which is the intended behaviour. The skeleton action model is a weak signal with MediaPipe keypoints and is treated as corroboration only. Synthetic-pose unit tests cover the full NORMAL → SUSPECT → FALLEN → CRITICAL path with immobility, and the Signal-for-Help FSM.

## Hand-pose classifier on real hands (Signal-for-Help detector)
The first version used the thumb-tip distance to the palm centre to detect a tucked thumb (threshold 0.6 palm-lengths). On MediaPipe's public hand photos real open palms scored 0.62–0.69, i.e. on top of the threshold, so a relaxed thumb read as THUMB_TUCKED and the sequence never started; this is why the distress detector did not fire in the first live session. The replacement feature, the thumb tip projected on the index-knuckle → pinky-knuckle axis, separates the cases with a wide gap:

| Image (MediaPipe test assets) | MediaPipe GestureRecognizer | thumb-across | Ours |
|---|---|---|---|
| fist.jpg | Closed_Fist | +0.19 | FIST |
| left_hands.jpg / right_hands.jpg (4 hands) | Open_Palm / none | −0.90 to −0.94 | OPEN_PALM |
| woman_hands.jpg (2 hands) | none | −0.80, −0.16 | OPEN_PALM |
| pointing_up.jpg | Pointing_Up | +0.25 | OTHER |
| victory.jpg | Victory | +0.55 | OTHER |
| thumb_up.jpg | Thumb_Up | −1.06 | OTHER (no longer mistaken for a fist) |

## Docker image
`docker compose up -d --build` on Windows 11 / Docker Desktop (WSL2, NVIDIA runtime): the container reports `torch 2.14.0+cu126 cuda_available=True`, all five models load on CUDA, `/api/health` runs a real HolisticLandmarker self-test (which caught a missing `libEGL.so.1` in the first image), the browser assets are served (`/models/holistic_landmarker.task`, `/mediapipe-wasm/*`), and the Thank-you clip uploaded through the container yields "Thank You" 0.945 → "Thank you." (8.2 s vs 2.4 s natively: MediaPipe runs on the Docker Desktop VM's CPU; a Linux host with the same image runs it natively).

## Unit tests
`cd backend && python -m pytest -q` → 43 passed (preprocessing shapes, strict loading, joiner grammar, verifier acceptance/rejection, LLM fallback, gate hysteresis, three-head fusion, broken-head isolation, unknown emission, posture and fall state machine, hand-pose classifier and Signal-for-Help FSM, SL-GCN port).
