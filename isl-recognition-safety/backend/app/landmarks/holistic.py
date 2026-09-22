"""Server-side landmark extraction with MediaPipe Tasks HolisticLandmarker (CPU).

Used for uploaded videos and for the browser fallback that sends JPEG frames.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

from .frame import LandmarkFrame

log = logging.getLogger(__name__)

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/holistic_landmarker/"
             "holistic_landmarker/float16/latest/holistic_landmarker.task")


class HolisticExtractor:
    """One instance per video stream (MediaPipe VIDEO mode needs monotonic timestamps)."""

    def __init__(self, model_path: Path):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import (HolisticLandmarker, HolisticLandmarkerOptions,
                                                   RunningMode)
        if not model_path.exists():
            raise FileNotFoundError(f"HolisticLandmarker model missing: {model_path} (download from {MODEL_URL})")
        self._mp = mp
        opts = HolisticLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=RunningMode.VIDEO,
            min_face_detection_confidence=0.3,
            min_pose_detection_confidence=0.5,
            min_hand_landmarks_confidence=0.5,
        )
        self._lm = HolisticLandmarker.create_from_options(opts)
        self._last_ts = -1
        self._lock = threading.Lock()

    def process(self, rgb: np.ndarray, t_ms: float) -> LandmarkFrame:
        h, w = rgb.shape[:2]
        ts = int(round(t_ms))
        with self._lock:
            if ts <= self._last_ts:          # timestamps must be strictly increasing
                ts = self._last_ts + 1
            self._last_ts = ts
            img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            res = self._lm.detect_for_video(img, ts)
        return LandmarkFrame.from_holistic_result(res, float(ts), w, h)

    def close(self) -> None:
        try:
            self._lm.close()
        except Exception:  # pragma: no cover
            pass
