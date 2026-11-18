# Research: pretrained safety-event detection from a single webcam (14 Sep 2026)

Research agent report. **[V]** = verified by fetching the source page or running code locally; **[I]** = inferred/estimated.

## 0. Headline findings
1. **pyskl ST-GCN++ (NTU-60, HRNet 2D COCO-17 keypoints) runs with plain torch, no mmcv.** Checkpoint `stgcnpp_ntu60_xsub_hrnet/j.pth` (5.85 MB) loads into a ~120-line torch-only reimplementation with `strict=True` (1,393,016 params). CPU latency ~63 ms per 100-frame, 2-person clip. **[V]**
2. A synthetic "stand → rotate to horizontal → lie still" sequence scored A43 falling = 0.82, but pure Gaussian-noise input also scores A43 falling at 0.54–0.77, and all-zeros scores A42 staggering 0.40. **[V]** The skeleton classifier is a useful fall signal but must be gated on keypoint quality and fused with geometric rules.
3. No Kinetics-400 class is a fall **[V]**; K700 has only "falling off bike"/"falling off chair". HMDB51 has `fall_floor` (index 12) and pyskl ships PoseC3D checkpoints fine-tuned on HMDB51 (69.4% top-1).
4. For the Signal-for-Help gesture, no ready-made open weights exist; build an FSM over hand landmarks (palm → thumb tucked → fist).

## 1. Skeleton-based action recognition (NTU RGB+D)
Licenses: pyskl Apache-2.0 [V]; NTU RGB+D dataset is academic/non-commercial. Weights are distributed under Apache-2.0 but derive from that dataset; seek legal advice for commercial deployment [I].

Checkpoints (`http://download.openmmlab.com/mmaction/pyskl/ckpt/...`) [V]:

| Model | Split | Input | Modality | Top-1 | URL suffix |
|---|---|---|---|---|---|
| ST-GCN++ | NTU60 xsub | HRNet 2D | joint | 89.3 | `stgcnpp/stgcnpp_ntu60_xsub_hrnet/j.pth` |
| ST-GCN++ | NTU60 xsub | HRNet 2D | bone | 92.3 | `stgcnpp/stgcnpp_ntu60_xsub_hrnet/b.pth` |
| ST-GCN++ | NTU120 xsub | HRNet 2D | joint / bone | 84.4 / 84.8 | `stgcnpp/stgcnpp_ntu120_xsub_hrnet/{j,b}.pth` |
| PoseC3D SlowOnly-R50 | NTU60 xsub | 2D heatmaps | joint | 93.7 | `posec3d/slowonly_r50_ntu60_xsub/joint.pth` |
| PoseC3D | HMDB51 | 2D heatmaps | joint | 69.4 | `posec3d/slowonly_r50_hmdb51_k400p/s1_joint.pth` |

xsub = cross-subject (the number that matters); xview = cross-camera-view (inflated).

Input format (from pyskl source) [V]: COCO-17 2D keypoints; `PreNormalize2D` (mode fix: x ← (x − w/2)/(w/2), y ← (y − h/2)/(h/2); joints with score ≤ 0.01 zeroed; score appended as 3rd channel) → `GenSkeFeat` (j = raw; b = joint − parent) → `UniformSampleFrames(clip_len=100)` (frames looped if fewer) → `FormatGCNInput(num_person=2, mode zero)` → tensor (N, M=2, T=100, V=17, C=3). Single person: zero-pad slot 2 (what training did); looping the same person into slot 2 shifts the calibration.

NTU RGB+D 60 class list (0-based index = A − 1) [V]: A1 drink water · A2 eat meal · A3 brushing teeth · A4 brushing hair · A5 drop · A6 pickup · A7 throw · A8 sitting down · A9 standing up · A10 clapping · A11 reading · A12 writing · A13 tear up paper · A14 wear jacket · A15 take off jacket · A16 wear a shoe · A17 take off a shoe · A18 wear on glasses · A19 take off glasses · A20 put on a hat · A21 take off a hat · A22 cheer up · A23 hand waving · A24 kicking something · A25 reach into pocket · A26 hopping · A27 jump up · A28 make a phone call · A29 playing with phone · A30 typing on a keyboard · A31 pointing to something · A32 taking a selfie · A33 check time · A34 rub two hands · A35 nod head/bow · A36 shake head · A37 wipe face · A38 salute · A39 put the palms together · A40 cross hands in front (say stop) · **A41 sneeze/cough · A42 staggering · A43 falling · A44 touch head (headache) · A45 touch chest (stomachache/heart pain) · A46 touch back (backache) · A47 touch neck (neckache) · A48 nausea or vomiting · A49 use a fan (feeling warm)** · A50 punching/slapping · A51 kicking other person · A52 pushing · A53 pat on back · A54 point finger at other person · A55 hugging · A56 giving something · A57 touch other person's pocket · A58 handshaking · A59 walking towards · A60 walking apart.

Safety-relevant: A41–A49 (medical), A42 staggering / A43 falling (primary), A50–A52 (violence, need 2 people), A23 hand waving and A22 cheer up (arms-up "help" motions), A40 cross hands "stop", A8/A9 (sit/stand transitions, useful to suppress false falls).

## 2. Video-level (RGB) models on Hugging Face
| Model | Data | License | Safety relevance |
|---|---|---|---|
| MCG-NJU/videomae-base-finetuned-kinetics | K400 | CC-BY-NC-4.0 | none (no fall/lying class) |
| facebook/timesformer-base-finetuned-k400/k600 | K400/K600 | CC-BY-NC-4.0 | none |
| microsoft/xclip-base-patch32 | K400 contrastive | MIT | zero-shot with custom prompts; zero-shot HMDB51 only 44.6%; softmax over prompts always picks something; corroborator only |
| HMDB51 community fine-tunes | HMDB51 | unspecified | unreliable provenance |

## 3. Dedicated fall detection
YOLO fall detectors (leeyunjai/yolo11-falldetect single-class, Roboflow hosted, etc.) are single-frame "person lying" detectors of unknown provenance/license; no velocity. Optional third opinion only.

Pose-based rule methods with published thresholds: YOLOv8-pose hackster project (falling if nose vertical velocity > 22 px/frame and torso angle > 20°; fallen if torso angle > 50° or bbox W/H > 1.25); PIFR (PLOS One 2025, 9 features, 91.4% F1 on URFD+MCFD); ElderFallGuard (arXiv 2505.11845, MediaPipe: prone pose > 3 s and motion drop > 2 s → alert); long-lie pilot (Sensors 2025). arXiv 2503.19501 has been withdrawn.

Verdict: pose-geometry rules give the *state* (upright/lying, height drop, immobility) robustly and explainably; ST-GCN++ gives the *event* (falling vs sitting down vs picking up) but is fooled by bad keypoints. Use both.

## 4. Distress gestures
- MediaPipe GestureRecognizer: Unknown, Closed_Fist, Open_Palm, Pointing_Up, Thumb_Down, Thumb_Up, Victory, ILoveYou (Apache-2.0).
- HaGRIDv2: 33 gestures + no_gesture; dataset CC BY-SA 4.0 variant; code BSD-3; YOLOv10 weights (AGPL via Ultralytics), ResNet/MobileNet classifiers.
- Signal for Help (Canadian Women's Foundation, 2020): palm up → thumb tucked → fingers fold over thumb. Two papers (91–94%), no maintained public weights. Build as an FSM: OPEN_PALM → THUMB_TUCKED (four fingers up, thumb across palm) → FIST, each held ≥ 4 frames, full cycle within 2.5 s; ≥ 2 cycles → CRITICAL, 1 cycle → WARNING. Help-waving: wrist above shoulder, ≥ 3 x-direction sign changes in 2 s with amplitude > 0.3 × shoulder width.

## 5–6. Temporal fusion, immobility, anomaly detection
No practical pretrained video anomaly detector for a single person at home exists (UCF-Crime/ShanghaiTech methods need I3D features and target crime scenes). Skip.

Signals (per frame, EMA-smoothed α≈0.3): torso_angle (shoulder-mid→hip-mid vs vertical), bbox_ratio W/H, head_height, hip_v (vertical hip velocity in torso-lengths/s), speed (mean joint speed), kp_quality (fraction of 17 joints with score > 0.3). ST-GCN++ probabilities p_fall, p_stagger, p_medical (A41, A44–A48), p_wave (A22+A23) every 0.5 s on the last 100 frames, only when kp_quality ≥ 0.7 for ≥ 80% of the window.

Suggested thresholds [I, calibrate]: lying: torso_angle > 60° and bbox_ratio > 1.0; upright: torso_angle < 30° and H/W > 1.8; sudden drop: hip_v > 1.5 torso-lengths/s downward or head_height falls > 0.5 within 1 s; frantic: speed > 2.0 torso-lengths/s sustained 2 s; immobile: speed < 0.05 torso-lengths/s for ≥ 10 s; long-lie: lying and immobile ≥ 60 s.

State machine with hysteresis: NORMAL → SUSPECT_FALL when (sudden-drop rule) or (p_fall EMA > 0.6); SUSPECT_FALL → FALLEN when lying holds ≥ 3 s within 5 s (else → NORMAL); FALLEN → CRITICAL when immobile ≥ 10 s or p_medical > 0.5, or immediately if help gesture fires; FALLEN/CRITICAL → RECOVERING only when upright holds ≥ 5 s (exit p_fall < 0.35). Parallel tracks: DISTRESS (help gesture), ABNORMAL_MOTION (frantic ≥ 2 s → WARNING), LONG_LIE (lying + immobile ≥ 60 s → CRITICAL). Majority vote over the last 5 classifier outputs, minimum event duration 1 s, per-event cooldown 30 s, "person absent" state freezes timers rather than resetting them.

## 7. Recommended stack
| Layer | Component | Cost | Why |
|---|---|---|---|
| Pose | MediaPipe Holistic 33 → COCO-17 | CPU ~30 ms/frame | already extracted for signing |
| Primary event | pyskl ST-GCN++ NTU60-xsub-hrnet joint (+ bone) standalone | 63 ms/clip CPU, every 0.5 s | best fall/stagger/medical discrimination; offline |
| Primary state | Geometric rules | negligible | explainable; gates the GCN; drives immobility/long-lie |
| Gesture | Hand-landmark FSM | negligible | Signal-for-Help, waving |
| Optional | X-CLIP zero-shot; PoseC3D-HMDB51 | GPU only | tie-breaking, never sole trigger |

## 8. Verified vs not
Verified: openmmlab URLs and accuracies, pyskl source semantics, checkpoint key layout and strict loading, local latency and the noise-→-"falling" behaviour, NTU-60/120 and HMDB51 label maps, K400/K700 fall labels, HaGRID classes/licences, MediaPipe gesture list/model URL, X-CLIP licence/FLOPs/zero-shot numbers, ElderFallGuard and PIFR details, rtmlib deps/licence. Not verified: Roboflow fall dataset licence, leeyunjai weights licence, Signal-for-Help public dataset URL, hackster thresholds, latency numbers other than the ST-GCN++ CPU measurement.
