"""Lazy, fault-tolerant model registry. A missing/broken checkpoint disables one head only."""
from __future__ import annotations

import csv
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import torch

from ..config import settings
from . import hwgat as hwgat_mod
from . import include_features
from . import stgcnpp as stgcn_mod
from .include_transformer import IncludeTransformer

log = logging.getLogger(__name__)


@dataclass
class HeadInfo:
    key: str
    name: str
    license: str
    dataset: str
    reported_accuracy: str
    vocab: list[str] = field(default_factory=list)
    loaded: bool = False
    error: str | None = None
    path: str = ""
    limitations: str = ""
    citation: str = ""

    def to_json(self, with_vocab: bool = False) -> dict[str, Any]:
        d = {"key": self.key, "name": self.name, "license": self.license, "dataset": self.dataset,
             "reported_accuracy": self.reported_accuracy, "vocab_size": len(self.vocab), "loaded": self.loaded,
             "error": self.error, "limitations": self.limitations, "citation": self.citation}
        if with_vocab:
            d["vocab"] = self.vocab
        return d


def pick_device() -> torch.device:
    if settings.device == "cpu":
        return torch.device("cpu")
    if settings.device == "cuda" or settings.device == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if settings.device == "cuda":
            log.warning("ISL_DEVICE=cuda requested but CUDA is not available; falling back to CPU")
    return torch.device("cpu")


class TopK(dict):
    """{"top": [{"label","index","p"}...], "latency_ms": float, "probs": np.ndarray}"""


class HWGATHead:
    info = HeadInfo(
        key="hwgat", name="HWGAT (Hierarchical Windowed Graph Attention Network)", license="MIT",
        dataset="FDMSE-ISL: 2,002 ISL words, 40,033 videos, 20 Deaf signers (RKMVERI). Signer-independent split.",
        reported_accuracy="93.86% top-1 / 99.19% top-5 on FDMSE-ISL test (signer-independent); 97.67% on INCLUDE when trained on INCLUDE (different checkpoint)",
        limitations="Isolated citation-form signs from the FDMSE dictionary; trained on frontal studio video with the full upper body visible. "
                    "Regional variants, coarticulated continuous signing and fingerspelling are outside its training distribution. "
                    "On 18 INCLUDE clips (different signers/corpus) it reached 8/18 top-1 in our test with well-separated confidences.",
        citation="Patra et al., 'Hierarchical Windowed Graph Attention Transformer Encoder and a Large Scale Dataset for Indian Sign Language Recognition', Pattern Analysis and Applications 28(3):148, 2025. https://github.com/suvajit-patra/sl-hwgat-demo",
    )

    def __init__(self, models_dir: Path, device: torch.device):
        self.device = device
        d = models_dir / "hwgat"
        ckpt = d / "model_best_loss.pt"
        cmap = d / "class_map_FDMSE.csv"
        self.info.path = str(ckpt)
        if not ckpt.exists() or not cmap.exists():
            raise FileNotFoundError(f"HWGAT files missing in {d} (need model_best_loss.pt and class_map_FDMSE.csv; run scripts/download_models.py)")
        rows = list(csv.reader(open(cmap, encoding="utf-8")))[1:]
        self.labels = [""] * len(rows)
        for r in rows:
            self.labels[int(r[0])] = r[1]
        self.info.vocab = list(self.labels)
        self.model = hwgat_mod.HWGATModel.from_checkpoint(str(ckpt), device)
        self.fp16 = settings.hwgat_fp16 and device.type == "cuda"
        self._lock = threading.Lock()

    @torch.no_grad()
    def predict(self, frames) -> TopK | None:
        x = hwgat_mod.preprocess(frames)
        if x is None:
            return None
        t0 = time.perf_counter()
        xt = torch.from_numpy(x)[None].to(self.device)
        with self._lock:
            if self.fp16:
                with torch.autocast("cuda", dtype=torch.float16):
                    logits = self.model(xt)
            else:
                logits = self.model(xt)
        probs = logits.float().softmax(-1)[0].cpu().numpy()
        return _topk(probs, self.labels, (time.perf_counter() - t0) * 1000)


class IncludeHead:
    info = HeadInfo(
        key="include", name="INCLUDE keypoint Transformer (AI4Bharat, IIT Madras)", license="MIT (code and checkpoints); dataset CC BY 4.0",
        dataset="INCLUDE: 263 ISL words, 4,287 videos, 7 Deaf signers (St. Louis School for the Deaf, Chennai), 1920x1080.",
        reported_accuracy="Paper: 85.6% (INCLUDE) best model; this checkpoint's stored validation score 0.835. Split is by video, not signer (signer-dependent).",
        limitations="Signer-dependent evaluation; expects a full-upper-body 1920x1080 framing (features are raw pixel coordinates); "
                    "trained on isolated clips. Used here as a second opinion on the 263 INCLUDE words only.",
        citation="Sridhar, Ganesan, Kumar, Khapra, 'INCLUDE: A Large Scale Dataset for Indian Sign Language Recognition', ACM Multimedia 2020. https://github.com/AI4Bharat/INCLUDE",
    )

    def __init__(self, models_dir: Path, device: torch.device):
        self.device = device
        d = models_dir / "include"
        ckpt = d / "include_no_cnn_transformer_large.pth"
        size = "large"
        if not ckpt.exists():
            ckpt = d / "include_no_cnn_transformer_small.pth"
            size = "small"
        lmap = d / "label_map_include.json"
        self.info.path = str(ckpt)
        if not ckpt.exists() or not lmap.exists():
            raise FileNotFoundError(f"INCLUDE files missing in {d} (run scripts/download_models.py)")
        m = json.load(open(lmap))
        self.labels = [""] * len(m)
        for k, v in m.items():
            self.labels[int(v)] = k
        self.info.vocab = list(self.labels)
        self.model = IncludeTransformer.from_checkpoint(str(ckpt), size, len(self.labels), device)
        self._lock = threading.Lock()

    @torch.no_grad()
    def predict(self, frames) -> TopK | None:
        feats = [include_features.preprocess(frames, swap) for swap in (False, True)]
        if feats[0] is None:
            return None
        t0 = time.perf_counter()
        xt = torch.from_numpy(np.stack(feats)).to(self.device)
        with self._lock:
            probs = self.model(xt).softmax(-1).mean(0).cpu().numpy()
        return _topk(probs, self.labels, (time.perf_counter() - t0) * 1000)


class SLGCNHead:
    info = HeadInfo(
        key="slgcn", name="OpenHands SL-GCN / Decoupled GCN (AI4Bharat)", license="Apache-2.0",
        dataset="INCLUDE: 263 ISL words, 4,287 videos, 7 Deaf signers (same corpus as the INCLUDE transformer).",
        reported_accuracy="93.5% top-1 on the INCLUDE test split (OpenHands paper, ACL 2022; split by video, signer-dependent)",
        limitations="Signer-dependent evaluation; raw normalised (x,y) coordinates so proportions depend on the source aspect ratio (trained on 16:9 INCLUDE video); "
                    "isolated clips only. Very confident (p≈1.0) on its own corpus, so its weight is capped in fusion.",
        citation="Selvaraj et al., 'OpenHands: Making Sign Language Recognition Accessible with Pose-based Pretrained Models across Languages', ACL 2022. https://github.com/AI4Bharat/OpenHands",
    )

    def __init__(self, models_dir: Path, device: torch.device):
        from . import slgcn as slgcn_mod
        self.device = device
        d = models_dir / "openhands"
        sd = d / "include_slgcn_state_dict.pt"
        classes = d / "include_slgcn_classes.json"
        self.info.path = str(sd)
        if not sd.exists() or not classes.exists():
            raise FileNotFoundError(f"SL-GCN files missing in {d} (need include_slgcn_state_dict.pt and include_slgcn_classes.json; run scripts/download_models.py)")
        self.raw_labels, self.labels = slgcn_mod.load_labels(classes)
        self.info.vocab = list(self.labels)
        self.model = slgcn_mod.SLGCN.from_state_dict(sd, len(self.labels), device)
        self._pre = slgcn_mod.preprocess
        self._lock = threading.Lock()

    @torch.no_grad()
    def predict(self, frames) -> TopK | None:
        x = self._pre(frames)
        if x is None or x.shape[1] < 4:
            return None
        t0 = time.perf_counter()
        xt = torch.from_numpy(x)[None].to(self.device)
        with self._lock:
            probs = self.model(xt).softmax(-1)[0].cpu().numpy()
        return _topk(probs, self.labels, (time.perf_counter() - t0) * 1000)


class ActionHead:
    info = HeadInfo(
        key="stgcnpp", name="ST-GCN++ skeleton action recognition (pyskl, NTU RGB+D 60)", license="Apache-2.0 (code/weights); NTU RGB+D dataset is research-only",
        dataset="NTU RGB+D 60: 56,880 clips, 40 subjects, 60 daily/medical/interaction actions, 2D COCO-17 keypoints from HRNet.",
        reported_accuracy="89.3% top-1 NTU60 cross-subject (joint modality)",
        limitations="Lab-recorded actions with the full body visible; webcam upper-body framing leaves leg joints missing, so the head is gated on keypoint quality. "
                    "Random noise scores as 'falling' with p≈0.5–0.8, so it is never the sole trigger for an alert.",
        citation="Duan et al., 'PYSKL: Towards Good Practices for Skeleton Action Recognition', ACM MM 2022. https://github.com/kennymckormick/pyskl",
    )

    def __init__(self, models_dir: Path, device: torch.device):
        self.device = device
        ckpt = models_dir / "stgcnpp" / "stgcnpp_ntu60_xsub_hrnet_j.pth"
        self.info.path = str(ckpt)
        if not ckpt.exists():
            raise FileNotFoundError(f"ST-GCN++ checkpoint missing: {ckpt} (run scripts/download_models.py)")
        self.labels = list(stgcn_mod.NTU60_LABELS)
        self.info.vocab = list(self.labels)
        self.model = stgcn_mod.STGCNpp.from_checkpoint(str(ckpt), device)
        self._lock = threading.Lock()

    @torch.no_grad()
    def predict(self, kpts: np.ndarray, scores: np.ndarray, width: int, height: int) -> TopK:
        x = stgcn_mod.preprocess(kpts, scores, width, height)
        t0 = time.perf_counter()
        xt = torch.from_numpy(x).to(self.device)
        with self._lock:
            probs = self.model(xt).softmax(-1)[0].cpu().numpy()
        return _topk(probs, self.labels, (time.perf_counter() - t0) * 1000, k=5)


def _topk(probs: np.ndarray, labels: list[str], latency_ms: float, k: int = 5) -> TopK:
    idx = np.argsort(-probs)[:k]
    return TopK(top=[{"label": labels[i], "index": int(i), "p": float(probs[i])} for i in idx],
                latency_ms=round(latency_ms, 1), probs=probs)


class ModelRegistry:
    def __init__(self, models_dir: Path | None = None):
        self.models_dir = Path(models_dir or settings.models_dir)
        self.device = pick_device()
        self.hwgat: HWGATHead | None = None
        self.include: IncludeHead | None = None
        self.slgcn: SLGCNHead | None = None
        self.action: ActionHead | None = None
        self.holistic_ok = (self.models_dir / "mediapipe" / "holistic_landmarker.task").exists()
        self.holistic_error = None if self.holistic_ok else "models/mediapipe/holistic_landmarker.task missing"
        self.infos: dict[str, HeadInfo] = {"hwgat": HWGATHead.info, "include": IncludeHead.info,
                                           "slgcn": SLGCNHead.info, "stgcnpp": ActionHead.info}

    def load_all(self) -> None:
        for key, enabled, cls in (("hwgat", settings.enable_hwgat, HWGATHead),
                                  ("include", settings.enable_include, IncludeHead),
                                  ("slgcn", settings.enable_slgcn, SLGCNHead),
                                  ("stgcnpp", settings.enable_stgcnpp, ActionHead)):
            info = self.infos[key]
            if not enabled:
                info.loaded, info.error = False, "disabled by configuration"
                continue
            t0 = time.perf_counter()
            try:
                head = cls(self.models_dir, self.device)
                setattr(self, {"hwgat": "hwgat", "include": "include", "slgcn": "slgcn", "stgcnpp": "action"}[key], head)
                info.loaded, info.error = True, None
                log.info("loaded %s on %s in %.1fs", key, self.device, time.perf_counter() - t0)
            except Exception as e:  # noqa: BLE001 - we want to keep serving without this head
                info.loaded, info.error = False, f"{type(e).__name__}: {e}"
                log.exception("failed to load %s", key)
        # Actually instantiate the landmarker once: the Linux wheel can import fine and still fail
        # to load its native library (e.g. missing libEGL), which would only surface on first use.
        if self.holistic_ok:
            try:
                from ..landmarks.holistic import HolisticExtractor
                ex = HolisticExtractor(self.models_dir / "mediapipe" / "holistic_landmarker.task")
                ex.close()
            except Exception as e:  # noqa: BLE001
                self.holistic_ok, self.holistic_error = False, f"HolisticLandmarker failed to initialise: {type(e).__name__}: {e}"
                log.exception("HolisticLandmarker self-test failed")

    def health(self) -> dict[str, Any]:
        d = {k: v.to_json() for k, v in self.infos.items()}
        d["holistic"] = {"loaded": self.holistic_ok, "error": self.holistic_error, "name": "MediaPipe HolisticLandmarker (Apache-2.0)"}
        return d
