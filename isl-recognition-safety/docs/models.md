# Model selection: what was chosen, what was rejected, and why

Research was done on 2026-09-14 across Hugging Face, GitHub, Papers with Code, arXiv, Zenodo, Kaggle and Roboflow; the full survey reports are in `docs/research/` (`isl-models.md`, `landmark-extraction.md`, `safety-detection.md`, `temporal-pipeline-and-llm.md`). Every model below was downloaded, loaded with `strict=True`, and run on real video on the development machine before being selected. Numbers we measured ourselves are in `docs/evaluation.md`.

## 1. Landmark extraction

**Selected: MediaPipe Tasks `HolisticLandmarker` (mediapipe 1.0.1 in Python; `@mediapipe/tasks-vision` 1.0.1 in the browser). Apache-2.0.**

* 33 pose + 21+21 hand + 478 face landmarks, ≈30 ms/frame on a laptop CPU. The GPU delegate is not available in Windows Python, so the CPU path is what everyone gets; in the browser the WebGL delegate is used.
* The `mediapipe_holistic` layout is what OpenHands, the Kaggle GISLR models and HWGAT were trained on; INCLUDE used MediaPipe Hands + BlazePose, which the same landmarks reproduce.
* The legacy `mediapipe.solutions.holistic` API used by every older ISL repo **no longer exists** in mediapipe ≥0.10.30; the Tasks `HolisticLandmarker` returned to Python in 0.10.33 and is what we use. The `.task` model bundle is 13.7 MB.

Rejected: rtmlib/RTMW whole-body (Apache-2.0, 133 keypoints; 4× slower on CPU, only worthwhile on GPU); Ultralytics YOLO-pose (AGPL-3.0, no hand keypoints); Sapiens (non-commercial v1, 1.5 B-param models, not real-time on 6 GB); OpenPose (non-commercial, no Windows/Python 3.12 build).

## 2. ISL word recognition

There is no pretrained *continuous* ISL recogniser with public weights (ISL-CSLTR, ISLTranslate, iSign and CISLR are datasets without released checkpoints; the only ISL translation model on Hugging Face, `manavdhamecha77/iSign-t5-pose-to-text`, reports single-digit BLEU and no license). Isolated-sign models are therefore combined with a heuristic segmenter (see `docs/pipeline.md`).

### Primary head: HWGAT — 2,002 words
* Source: https://github.com/suvajit-patra/sl-hwgat-demo (MIT). Weights `model_best_loss.pt` (216 MB zip on Google Drive, fetched with `gdown`). Paper: Patra et al., *Hierarchical Windowed Graph Attention Transformer Encoder and a Large Scale Dataset for Indian Sign Language Recognition*, Pattern Analysis and Applications 28(3):148, 2025 (arXiv 2407.14224).
* Dataset: FDMSE-ISL (RKMVERI) — 2,002 words, 40,033 videos, 20 Deaf signers, **signer-independent split** (10 train / 2 val / 8 test signers). Reported 93.86% top-1, 99.19% top-5.
* Input: MediaPipe Holistic → 29 keypoints (nose, eyes, shoulders, elbows, wrists + 10 per hand), x/y only, nose-origin/shoulder-width normalisation, 192 frames, assembled into four 16-keypoint body-part windows. Our port (`backend/app/models/hwgat.py`) reproduces the demo preprocessing bit-exactly (max abs diff 0.0 on a real clip) and loads the checkpoint strictly. 20.5 M parameters; 43 ms/clip on the RTX 3060 (21 ms fp16), ≈0.8 s on CPU.
* Vocabulary includes the safety words the app needs (Help, Dangerous, Police, Pain, Hurt, Doctor, Hospital, Ambulance, Fire, Attack, Stop, Sick, Accident, Urgent, Thief, Gun, Knife, Alone…) and everyday words (Water, Want, Need, Eat, Home, Mother, Father, greetings, question words, numbers, days, places).
* Caveats: citation-form dictionary signs; regional variants and continuous signing are out of distribution. On INCLUDE clips (different corpus) it scored 8/18 top-1 in our test; its confidence is well separated (≥0.7 on hits, ≤0.3 on misses).

### Second head: INCLUDE keypoint Transformer — 263 words
* Source: https://github.com/AI4Bharat/INCLUDE (MIT). Checkpoint `include_no_cnn_transformer_large.pth` (206 MB, Weights & Biases public files; the `use_cnn` links in the repo are dead placeholders). Paper: Sridhar, Ganesan, Kumar, Khapra, *INCLUDE: A Large Scale Dataset for Indian Sign Language Recognition*, ACM Multimedia 2020.
* Dataset: INCLUDE (IIT Madras, Zenodo 4010759, CC BY 4.0) — 263 words in 15 categories, 4,287 videos, 7 Deaf signers, 1920×1080; the split is by video, so accuracy is **signer-dependent**. Paper best 85.6%; this checkpoint stores a validation score of 0.835.
* Input: 25 upper-body pose points + 2×21 hand points, x/y in 1920×1080 pixel space, NaN-interpolated, zero-padded to 169 frames (from the repo's `evaluate.py`). The BERT encoder layers were reimplemented in plain PyTorch (`include_transformer.py`) because the reference depends on a `transformers.BertLayer` API that no longer works standalone; equivalence against the reference under transformers 4.57 is exact (max abs diff 0.0 once the reference's inference-time dropout — a bug in the upstream `evaluate.py` — is disabled). Hand order was arbitrary in the upstream training data, so we average the softmax over both hand orders.
* Role: independent second opinion whose weight scales with its own confidence; 223 of its 263 labels map onto HWGAT labels by alias (`vocab.py`).

### Third head (optional): OpenHands SL-GCN — 263 words
* Source: https://github.com/AI4Bharat/OpenHands (Apache-2.0, unmaintained since 2023). Release zip `include_slgcn.zip` (40.6 MB, Lightning checkpoint). Paper: Selvaraj et al., *OpenHands: Making Sign Language Recognition Accessible with Pose-based Pretrained Models across Languages*, ACL 2022. Reported 93.5% on the INCLUDE test split (signer-dependent).
* Input: `mediapipe_holistic_minimal_27` preset (27 of the 75 pose+hand points), shoulder-centred/shoulder-scaled. The class order is not stored in the checkpoint; it was recovered from `Train_Test_Split.zip` inside OpenHands' Zenodo INCLUDE archive (record 6674324): `sorted(set(df["Word"]))`.
* Status: **enabled by default.** The port (`backend/app/models/slgcn.py`) matches the original OpenHands code to max abs diff 0.0 on the same input, loads the converted state dict strictly (342 tensors), and scored 16/18 top-1 on the INCLUDE test clips (25 ms/clip GPU, 39 ms CPU). `scripts/download_models.py` fetches the release zip and converts the Lightning checkpoint without needing Lightning. Because it and the INCLUDE transformer share the same 7-signer corpus and the SL-GCN is extremely confident on that corpus (p ≈ 1.0), their fusion weights are 0.25 and 0.15 against HWGAT's 0.6 (each scaled by its own confidence).

### Rejected ISL candidates (and why)
| Candidate | Why not |
|---|---|
| Sooryak12 LSTM (the earlier `isl-backend`) | 3 words, one signer |
| `Hemg/Indian-sign-language-classification` ViT, `ranveerphakade`/`meghmodi` landmark models, Roboflow alphabet detectors | Static alphabet/digits from studio still images; no evidence of webcam transfer; Roboflow weights need an API key. Fingerspelling is therefore not shipped rather than faked. |
| `Creator-090/isl-swin3d-model` | 76 words, 66.8% top-1, RGB Swin3D, gated |
| `cdsteameight`, `g-magdy`, `sunilsarolkar` Keras blobs | Undocumented input layout / OpenPose dependency |
| iSign T5 pose-to-text | Single-digit BLEU, no license, demo-grade |
| `signon-project/slr-poseformer-isl` | Irish Sign Language, not Indian |
| Google GISLR (250 signs), WLASL, SignCLIP, Uni-Sign, SignLLM, SignGemma | American/other sign languages; none cover ISL |
| islkit (PyPI) | Ships no weights |
| Ishaara AI | No public API |

## 3. Safety detection

### ST-GCN++ (pyskl) — NTU RGB+D 60
* Source: https://github.com/kennymckormick/pyskl (Apache-2.0). Checkpoint `stgcnpp_ntu60_xsub_hrnet/j.pth` (5.85 MB, download.openmmlab.com), 89.3% top-1 cross-subject. Paper: Duan et al., *PYSKL: Towards Good Practices for Skeleton Action Recognition*, ACM MM 2022.
* Input: COCO-17 2D keypoints normalised to [-1,1], 100 frames (looped if fewer), 2-person slot zero-padded. Ported to plain PyTorch (`stgcnpp.py`, strict load, no mmcv).
* Relevant classes: falling (A43), staggering (A42), sneeze/cough, headache, chest/back/neck pain, nausea (A41, A44–A48), hand waving / cheer up (A22–A23).
* Caveats found in testing: random noise scores as "falling" (p 0.5–0.8) and a person standing still on the UR Fall camera scored "kicking something" 0.99; normal walking scored "staggering" 0.6–0.7. The head therefore runs only when ≥80% of frames have ≥70% of joints visible, its outputs are 5-vote averaged, staggering must be sustained 3 s with real motion, medical cues must be sustained 4 s, and no alert is raised by this head alone. NTU RGB+D itself is licensed for research use only.

Rejected: VideoMAE / TimeSformer Kinetics models (no fall class, CC-BY-NC), X-CLIP zero-shot (MIT but 44.6% zero-shot on HMDB51 and always picks something), YOLO "fall" detectors on Hugging Face/Roboflow (single-frame lying detectors, unknown provenance and license), pretrained video-anomaly detectors (UCF-Crime style, need I3D features, wrong domain), HaGRID gesture models (YOLOv10 route is AGPL; the Signal-for-Help sequence is easier to express geometrically).

### Rules and state machines (no weights)
Posture geometry (torso angle, box ratio, hip velocity, head drop, speed, immobility), the Signal-for-Help FSM (open palm → thumb tucked → fist), help-waving, the recognised-sign safety lexicon and the fusion state machine are described in `docs/pipeline.md`. Thresholds come from the fall-detection literature summarised in `docs/research/safety-detection.md` and were checked on the UR Fall Detection sequences (`docs/evaluation.md`).

## 4. Gloss → English

* Deterministic joiner (always): ISL is SOV, lacks articles/copula, puts time first and the question sign last (Zeshan 2003; Aboh, Pfau & Zeshan 2005).
* Optional LLM polish: Anthropic Claude via the official SDK (`claude-opus-5` by default, JSON-schema `output_config`, effort low) or a local Ollama model. Fine-tuned gloss-to-text systems (Gloss2Text on PHOENIX, SignLLM) do not exist for ISL and would need training.
* Grounding verifier: rejects any sentence with an ungrounded content word, a dropped gloss, or a wrong number of `[unknown sign]` markers. Zero-shot LLM gloss translation is known to over-generate (see `docs/research/temporal-pipeline-and-llm.md`), which is why verification is mandatory rather than optional.

## 5. Licenses at a glance
| Component | License |
|---|---|
| Application code | MIT |
| MediaPipe (models + Python/JS packages) | Apache-2.0 |
| HWGAT code + weights | MIT |
| INCLUDE code + weights | MIT (dataset CC BY 4.0) |
| OpenHands code + weights | Apache-2.0 |
| pyskl ST-GCN++ code + weights | Apache-2.0 (NTU RGB+D dataset: research-only terms) |
| Anthropic SDK | MIT |
