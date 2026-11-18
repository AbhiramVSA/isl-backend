# Research: landmark-extraction stack (14 Sep 2026)

Research agent report. **[V]** = verified by fetching the source, parsing PyPI/npm JSON, inspecting wheel contents, or running code on this machine (Python 3.12.4, RTX 3060 Laptop, driver 581.57 / CUDA 13.0). **[I]** = inferred.

## Comparison table

| Stack | Keypoints | CPU speed (640×480) | GPU speed | Install | License | Py3.12 Win? | JS? |
|---|---|---|---|---|---|---|---|
| MediaPipe Tasks HolisticLandmarker | 33 pose (+33 world) + 21+21 hands + 478 face | **28–32 ms (~32 fps)** [V] | No GPU on Windows Python [V] | `pip install mediapipe==1.0.1` | Apache-2.0 [V] | Yes [V] | Yes, `@mediapipe/tasks-vision@1.0.1` [V] |
| MediaPipe Hand / Pose / Face (separate tasks) | 21/hand; 33 pose; 478 face | Hand 22–28 ms; Pose lite 13 / full 19 / heavy 63 ms; Face 9 ms [V] | same | same | Apache-2.0 | Yes | Yes |
| rtmlib Wholebody (YOLOX + RTMW) | 133 COCO-WholeBody | lightweight 122 ms; balanced 373 ms [V] | lightweight 44 ms; balanced 69 ms via ORT CUDA [V] | `rtmlib==0.0.16` + `onnxruntime-gpu==1.30.0` | Apache-2.0 [V] | Yes | No |
| Ultralytics YOLO11-pose | 17 COCO body, no hands/face | n: 52 ms CPU ONNX | 1.7 ms T4 TRT | `pip install ultralytics` | **AGPL-3.0** | Yes | Yes |
| Sapiens v1 / Sapiens2 | 308 whole-body, 1024×768 | not real-time | 0.4B–5B params | conda/torch | v1 CC-BY-NC 4.0; v2 custom | untested | No |
| OpenPose | BODY_25 + 2×21 + 70 face | – | CUDA/Caffe build | CMake | non-commercial | effectively no | No |

## MediaPipe (Python) — verified
- Latest **1.0.1** (2026-08-14); wheels are ABI-agnostic `py3-none-win_amd64`. Deps: absl-py, numpy (unpinned), opencv-contrib-python, flatbuffers, sounddevice, matplotlib. No protobuf/jax. Works with numpy 2.5.
- **Legacy `mediapipe.solutions` is gone** from 0.10.30 onward. 0.10.21 is the last release with it (cp312 wheels exist; needs numpy<2, protobuf<5).
- **HolisticLandmarker Python task** present from 0.10.33 onward; on 1.0.1 outputs 33 pose + 33 pose-world + 478 face + 21 + 21 at ~30 ms/frame CPU.
- GPU delegate on Windows Python raises `NotImplementedError` — CPU (XNNPACK) only.
- Model URLs verified (HTTP 200): hand_landmarker (7.8 MB), pose_landmarker lite/full/heavy (5.8/9.4/30.7 MB), face_landmarker (3.8 MB), holistic_landmarker (13.7 MB), all under `https://storage.googleapis.com/mediapipe-models/...`.
- Gotcha: standalone FaceLandmarker misses faces on wide frames; Holistic derives the face ROI from pose and does better. Holistic face has 478 points (GISLR used 468).

## MediaPipe JS
- npm `@mediapipe/tasks-vision` **1.0.1**, Apache-2.0; exports HolisticLandmarker, HandLandmarker, PoseLandmarker, FaceLandmarker, GestureRecognizer; `delegate: "GPU"` = WebGL. WASM from `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1/wasm`.
- Landmarks-only upload: 543 points × 3 float32 ≈ 6.5 KB/frame (~195 KB/s at 30 fps).

## rtmlib / RTMW
- rtmlib 0.0.16, Apache-2.0; `Wholebody(mode, backend='onnxruntime', device)`. Measured CUDA lightweight 44 ms, balanced 69 ms; CPU 122/373 ms. 4× slower than Holistic on CPU; optional GPU path only.

## YOLO11-pose: AGPL-3.0, no hands. Sapiens: too heavy / non-commercial. OpenPose: dead on Windows/py3.12.

## Keypoint formats in SLR work
- INCLUDE (repo): MediaPipe Hands + BlazePose, 134 features. OpenHands: MediaPipe Holistic, 75 points, `mediapipe_holistic_minimal_27` preset `[0,2,5,11,12,13,14,33,37,38,41,42,45,46,49,50,53,54,58,59,62,63,66,67,70,71,74]`, shoulder-centre/scale normalisation. Kaggle GISLR: 543 rows/frame (face 0–467, left hand 468–488, pose 489–521, right hand 522–542).

## Compatibility gotchas
1. `onnxruntime` + `onnxruntime-gpu` installed together silently disable CUDA; install `onnxruntime-gpu` alone with `--no-deps`.
2. onnxruntime-gpu 1.30.0 targets CUDA 13 / cuDNN 9 (pip-installable nvidia-* packages, ~1.5 GB); call `onnxruntime.preload_dlls()`.
3. mediapipe pulls `opencv-contrib-python` (5.0.0.93 resolved); avoid also installing `opencv-python`.
4. MediaPipe Windows Python is CPU only: ~1 core per 30 fps stream.

## Recommendation
- Server: MediaPipe Tasks HolisticLandmarker (CPU, ~30 ms/frame), VIDEO running mode with monotonic timestamps.
- Browser: `@mediapipe/tasks-vision@1.0.1` HolisticLandmarker with GPU (WebGL) delegate; send only landmarks over WebSocket.
- Pins: `mediapipe==1.0.1`, `numpy>=2,<3`.
