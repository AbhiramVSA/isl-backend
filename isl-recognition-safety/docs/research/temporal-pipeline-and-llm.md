# Research: continuous-signing pipeline and gloss-to-English LLM layer

Research agent report, 2026-09-14. Items marked **[verified]** were read from the cited page on that date; **[inferred]** is engineering judgment.

---

## GOAL A — Isolated classifier → live continuous signing (no training)

### A1. The one real pretrained sign-boundary segmenter: `sign-language-processing/segmentation`

This is the only off-the-shelf model found that actually outputs *sign boundaries* rather than "signing / not signing".

- Repo: https://github.com/sign-language-processing/segmentation — paper "Linguistically Motivated Sign Language Segmentation" (Moryossef et al., Findings of EMNLP 2023, https://arxiv.org/abs/2310.13960). BIO tagging for both *sign* and *phrase* boundaries from MediaPipe Holistic poses; reports zero-shot generalisation to a different signed language **[verified, abstract]**.
- Install: `pip install git+https://github.com/sign-language-processing/segmentation` (not on PyPI) **[verified]**.
- `pyproject.toml`: `requires-python >=3.11`; deps `pose-format>=0.8.1, numpy, pympi-ling, torch, pose-anonymization, scikit-learn, pytorch-lightning, safetensors`; weights ship inside the package (`sign_language_segmentation/dist/2026/{config.json, model.safetensors}`) **[verified]**. README states MIT.
- `config.json`: `pose_dims [50, 6]`, `hidden_dim 384`, `encoder_depth 4`, `num_classes 4`, `num_frames 1024` **[verified]**. Two-stage UNet CNN + Transformer with RoPE, emitting BIO tags for sign and phrase tiers. The 6 dims are x,y,conf plus per-frame velocity.
- API: `run_inference()` returns per-frame log-probs; `segment_pose()` converts to `tiers = {"SIGN": [{"start","end"}], "SENTENCE": [...]}` in frame indices **[verified]**.
- Input: a `pose-format` `.pose` from MediaPipe Holistic (legacy solution). Safer route: construct the `Pose` object from your own landmark arrays.
- Real-time caveat: the model is bidirectional (not causal). Run it on a trailing buffer and only commit segments that end ≥0.3 s before the buffer's end. Zero-shot transfer was shown for another signed language, not specifically ISL.

### A2. Google's sign-language *detection* (Moryossef et al. 2020)

- Live repos: `sign-language-processing/detection-train` (Keras `models/py/model.h5`, TF.js `models/js/model.json`, MIT) and `detection-app`. Paper https://arxiv.org/abs/2008.04637.
- Method: optical flow computed from pose keypoints, normalised by shoulder width and frame rate; single-layer LSTM; 91.5% accuracy on DGS Corpus; 3.5 ms/frame.
- Output is a per-frame **is-signing probability**: an activity gate, not sign boundaries. Reproducible in ~10 lines with pose velocity + hysteresis.

### A3. How GISLR winners and PopSign "segment" — they don't

The Kaggle GISLR task is *isolated clips* (250 ASL signs); PopSign has the player sign one word per game turn. 1st place = 1D-CNN + Transformer on landmarks (https://github.com/hoyso48/Google---Isolated-Sign-Language-Recognition-1st-place-solution). The fingerspelling winner uses Squeezeformer + CTC on pre-cut phrase clips. Takeaway: the recipe is "gate + window".

### A4. Pretrained-free segmentation signals (from landmarks)

1. **Hand presence**: hand landmarks missing for ≥5 consecutive frames → not signing.
2. **Rest pose**: wrist `y` below hip `y` (Pose 23/24), or wrists within ~0.15 shoulder-widths of torso midline and below shoulder line for ≥10 frames → rest.
3. **Motion energy**: per-frame sum of ‖Δ(landmark)‖ over both hands, normalised by shoulder width and dt. Median-smooth (5 frames). Hysteresis: `on` when > θ_hi for 3 frames, `off` when < θ_lo for 8 frames.
4. **Pause = boundary**: energy local minimum below θ_lo for ≥4 frames, or sharp hand-shape change with near-zero position velocity.
5. **Sliding window**: windows of the classifier's training length, stride ~8 frames; only score windows where the gate is on. Pad/resample exactly as at train time.
6. **Stable-segment-only classification** (coarticulation suppression): score a window only when it is a hold/stroke rather than a transition. Single biggest error reducer for isolated classifiers on continuous input.

### A5. Prediction smoothing and emission

- **EMA on probability vectors**: `p̄ ← α·p̄ + (1−α)·p`, α≈0.7.
- **Agreement**: top-1 identical for K=3 consecutive windows, `p̄_top1 ≥ 0.6`, margin `p̄_top1 − p̄_top2 ≥ 0.2`. Otherwise emit nothing.
- **Unknown**: entropy above ~0.6·log(C), or margin < 0.1 while the gate is on for ≥0.5 s → emit `UNKNOWN`. Isolated classifiers have no reject class.
- **Debounce**: emit on the rising edge of a stable prediction; suppress the same gloss until the gate cycles off/on, energy dips and rises again (reduplicated signs), or ≥1.5 s elapsed.
- **Sentence boundary**: hands at rest / gate off for 1.0–1.5 s; also flush on a hard cap (~12 glosses).
- **Low-confidence marker**: carry per-gloss confidence; 0.4–0.6 gets a `?` marker.

### A6. Fingerspelling assembly

- Hold: accept a letter after ≥0.25 s top-1 with margin ≥0.2.
- Repeated letters are usually one longer articulation or a lateral shift, not two copies; do not double on hold duration alone.
- Word end: hand drops / gap >0.5 s. Emit as a single `FS(word)` token so the translator copies it verbatim.

---

## GOAL B — Safest gloss → English architecture

### B1. Literature and failure modes

- **Gloss2Text** (Findings EMNLP 2024, https://arxiv.org/abs/2407.01394): fine-tunes NLLB-200/mT5/mBART on PHOENIX-2014T; notes gloss ambiguity. Fine-tuned, not reusable for ISL.
- **SignLLM** (CVPR 2024, https://arxiv.org/abs/2404.00925): gloss-free, needs training.
- Zero-shot LLM gloss translation studies report **overgeneration and inconsistency** as the dominant problems. LLM-as-recogniser evals show open-set gloss identification is weak (https://arxiv.org/pdf/2510.08482) — a reason never to let the LLM guess an UNKNOWN sign.
- Failure modes to design against: filling gaps with plausible content words; silently dropping `UNKNOWN`; confidently resolving ambiguity; reordering that changes meaning; prose instead of JSON.

### B2. Recommended contract

**Deterministic joiner (always available).** ISL is SOV; no articles/copula; single sentence-final wh-sign (Aboh, Pfau & Zeshan 2005; ACM TALLIP "Sign Language Generation System Based on ISL Grammar" https://dl.acm.org/doi/10.1145/3384202). Joiner: SOV→SVO; insert copula between pronoun and adjective/noun; wh at end → fronted; `NOT` after verb → "do not V"; time sign → tense; `FS(x)` verbatim; `UNKNOWN` → `[unknown sign]`; `?`-marked → `word(?)`.

**Optional LLM polish** with a strict system prompt: every content word must correspond to an input gloss; only allowlisted function words may be added; copy `FS(x)` verbatim; preserve `UNKNOWN` as `[unknown sign]`; return JSON only; return `ok:false` rather than invent.

**Post-generation verification (mandatory):** parse JSON; lemmatise output tokens; each must be in {input gloss lemmas} ∪ {function-word allowlist} ∪ punctuation; `[unknown sign]` count equals `UNKNOWN` count; every input content gloss appears; otherwise fall back to the joiner and log.

### B3. Provider comparison (verified 2026-09-14 at platform.claude.com)

| Model | ID | $/MTok in/out |
|---|---|---|
| Claude Haiku 4.5 | `claude-haiku-4-5` | 1 / 5 |
| Claude Sonnet 5 | `claude-sonnet-5` | 2 / 10 |
| Claude Opus 5 | `claude-opus-5` | 5 / 25 |
| Claude Fable 5.1 | `claude-fable-5-1` | 10 / 50 |

~350 prompt + ~60 output tokens per sentence → well under a cent per sentence on any tier. Latency ~0.5–1.5 s. Local Ollama (qwen2.5:3b / llama3.2:3b) ≈3 s per sentence on modest hardware; small models violate grounding more often, so the verifier matters more offline.

Privacy: only the gloss list (strings + confidences) leaves the machine; never frames or landmarks.

### B4. Recommended design

1. Pose-velocity gate + rest-pose detector; optionally the segmentation model's SIGN tier on a trailing buffer.
2. Classifier on stable windows; EMA + K=3 agreement + margin; `UNKNOWN` via entropy; rising-edge debounce.
3. Deterministic joiner runs first and is displayed immediately; LLM called asynchronously with the strict JSON contract; its output replaces the joiner's only if the grounding verifier passes.
4. UI preserves `[unknown sign]` and `word(?)` markers end-to-end.

### Sources
- https://github.com/sign-language-processing/segmentation · https://arxiv.org/abs/2310.13960 · https://github.com/sign-language-processing/pose
- https://github.com/sign-language-processing/detection-train · https://arxiv.org/abs/2008.04637
- https://github.com/hoyso48/Google---Isolated-Sign-Language-Recognition-1st-place-solution · https://www.kaggle.com/competitions/asl-signs
- https://arxiv.org/abs/2407.01394 · https://arxiv.org/abs/2404.00925 · https://arxiv.org/pdf/2510.08482
- https://dl.acm.org/doi/fullHtml/10.1145/3384202
- https://platform.claude.com/docs/en/about-claude/models/overview · https://docs.ollama.com/capabilities/structured-outputs
