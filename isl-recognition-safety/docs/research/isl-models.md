# Research: downloadable Indian Sign Language (ISL) models (14 Sep 2026)

Research agent report. Only things that exist as downloadable weights today, verified by opening repos/model pages and HTTP-probing weight URLs. "ISL" always means Indian Sign Language.

## 1. AI4Bharat INCLUDE (IIT Madras) — official repo
- https://github.com/AI4Bharat/INCLUDE (MIT, last commit 2021-05-16). Dataset https://zenodo.org/records/4010759 (CC BY 4.0, 56.8 GB, 4,292 videos, 263 words / 15 categories, 7 Deaf signers). INCLUDE-50 subset = 50 words.
- Features: MediaPipe Hands + BlazePose (legacy), 134 features/frame (25 upper-body pose xy + 2 hands × 21 xy), padded to 169 frames.
- Checkpoints on wandb (verified): large transformer (205.8 MB), small transformer (46.2 MB), LSTM (87 MB), plus INCLUDE-50 variants. `use_cnn` links are dead placeholders.
- Paper (ACM MM 2020): 94.5% INCLUDE-50 / 85.6% INCLUDE. Split is by video, not by signer → signer-dependent. Recorded validation scores inside the checkpoints: large 0.835, small 0.813, LSTM 0.562.
- Verdict: usable; expect real-world accuracy well below 85%.

## 2. AI4Bharat OpenHands — pose-based INCLUDE checkpoints
- https://github.com/AI4Bharat/OpenHands (Apache-2.0, last commit 2023-03-15, "no longer actively maintained").
- Release zips verified: include_lstm (18.8 MB), include_bert (42 MB), include_slgcn (40.6 MB), include_stgcn (32.3 MB), include_dpc (35.6 MB; self-supervised on 1,129 h of ISL YouTube video then fine-tuned).
- Input: 27 MediaPipe Holistic 2-D keypoints/frame (`mediapipe_holistic_minimal_27`), shoulder-centred normalisation.
- Reported INCLUDE test accuracy (ACL 2022): LSTM 83.0, BERT 90.4, ST-GCN 91.2, SL-GCN 93.5, DPC-finetuned 94.7 (signer-dependent split).
- Caveats: PyPI `OpenHands` is now an unrelated package; code targets Lightning 1.x.

## 3. HWGAT + FDMSE-ISL (RKMVERI) — largest downloadable ISL vocabulary
- Code https://github.com/suvajit-patra/sl-hwgat (MIT); demo https://github.com/suvajit-patra/sl-hwgat-demo (MIT, Flask API + camera demo). Paper https://arxiv.org/abs/2407.14224.
- Dataset FDMSE-ISL: 2,002 words, 40,033 videos, 20 Deaf signers, signer-independent split (10/2/8). Dataset request-only; model public.
- Weights: Google Drive `best_model_and_FDMSE_class_map.zip` (216 MB), contains `model_best_loss.pt` + `class_map_FDMSE.csv`.
- Input: MediaPipe Holistic → 29 keypoints (9 pose + 10 per hand), x/y only, nose-origin / shoulder-normalised, 192-frame sample.
- Accuracy: FDMSE-ISL top-1 93.86% (top-5 99.19%) signer-independent; INCLUDE 97.67%.
- Verdict: top pick for coverage.

## 4. iSign / CISLR / ISLTranslate (IIT Kanpur)
- ISLTranslate: dataset-only (CC BY-NC 4.0), no checkpoints. iSign (ACL 2024): 228 GB gated dataset, no released checkpoints; ISLR baseline top-1 16.81%. CISLR: gated dataset, no weights.
- Only downloadable ISL translation model: https://huggingface.co/manavdhamecha77/iSign-t5-pose-to-text (T5 pose-to-text, single-digit BLEU-4, no license). Demo-grade only.

## 5. Continuous ISL corpora
- ISL-CSLTR (100 sentences, 7 signers): no baseline code or weights. ISL-FS fingerspelling: no checkpoints. Dead end for no-training.

## 6. Sooryak12/Indian-Sign-Language-Recognition
- 3 signs (Hello, How are you, Thank you), single signer, Keras LSTM. Toy.

## 7. Hugging Face models (search "indian sign language")
| Model | Vocab | Input | License | Verdict |
|---|---|---|---|---|
| Hemg/Indian-sign-language-classification | 35 static (1-9, A-Z) | image, ViT-B/16 | Apache-2.0 | works; unknown dataset |
| cdsteameight/ISL-SignLanguageTranslation | INCLUDE words, undocumented | video | MIT | impractical |
| sunilsarolkar/isl-translation-model | 167 INCLUDE classes | OpenPose Body25 | MIT | needs OpenPose |
| meghmodi/Indian-Sign-Language-KairoAI | static A-Z | 63 hand landmarks, tflite | none | tiny, unverified |
| ranveerphakade/ISL-Sign-Lang-Detection | static 36 | hand landmarks, .h5 | MIT | runnable |
| Creator-090/isl-swin3d-model | 76 words | RGB, Swin3D | gated | 66.8% top-1, heavy |
| signon-project/slr-poseformer-isl | Irish SL | — | — | not Indian |

## 8. Roboflow Universe
- Alphabet/digit detectors (35 classes, CC BY 4.0) exist but weights cannot be downloaded anonymously; hosted inference needs an API key. GitHub repos with YOLOv5 alphabet weights: BiJu-02/ISL-Yolov5, Tanwar-12/Indian_Sign_Language_Detection-Yolov5 (no license).

## 9. GitHub word-level MediaPipe projects with weights
- nvaltryek-001/Indian-Sign-Language-Recognition: INCLUDE-50 hand-only LSTM (50 words, no license).
- Static-alphabet repos: MaitreeVaria (FNN on 42 landmarks), sompuradhruv, AbhishekSinghDhadwal (GPL-3.0).
- islkit (PyPI): no pretrained weights shipped.

## 10. Kaggle: datasets only (prathumarikeri ISL 35 classes, eraakash landmarks, kaushikyh 80 INCLUDE words with landmarks). No weights.

## 11. ASL / other-language models — explicitly NOT ISL
- Google GISLR (250 ASL signs), WLASL (ASL, non-commercial), SignCLIP (41 languages, zero-shot ISLR recall@1 ≈ 0.01), Uni-Sign, SignLLM, SpaMo, SignGemma: none cover ISL.

## 12. Commercial / hosted APIs
- Ishaara AI (Mumbai): no public API. No cloud vendor offers ISL recognition.

## Ranked recommendation
1. HWGAT (2,002 words, signer-independent 93.9%, MIT).
2. OpenHands INCLUDE SL-GCN / DPC (263 words, Apache-2.0) as a second opinion.
3. INCLUDE transformer (46/206 MB wandb) — cheapest 263-word fallback.
4. Static fingerspelling head (Hemg ViT or landmark models).
5. Optional demo only: iSign T5 pose-to-text.

Dead ends: iSign/CISLR/ISLTranslate (no checkpoints), ISL-CSLTR, islkit, Roboflow, Sooryak12, Swin3D, Irish SL, all ASL models, Ishaara.
