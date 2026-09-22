"""INCLUDE feature extraction (AI4Bharat, MIT) reproduced from generate_keypoints.py + evaluate.py.

Per frame 134 features: 25 upper-body pose points (x,y) + hand1 (21 x,y) + hand2 (21 x,y),
scaled to 1920x1080 pixel coordinates (the INCLUDE videos' resolution). Missing parts are NaN and
linearly interpolated along time (both directions); all-NaN columns become 0. The sequence is
zero-padded to 169 frames (upstream evaluate.py).

Upstream assigns "hand1" to the hand nearest the *left* wrist and "hand2" to the hand nearest
the *right* wrist when only one hand is detected; with two hands it kept MediaPipe Hands' order,
which is arbitrary. We use MediaPipe Holistic's handedness (hand1 = person's left) and, at
inference, average the softmax over both hand orders (test-time augmentation) to be robust to
that training-time ambiguity.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from ..landmarks.frame import LandmarkFrame

MAX_FRAMES = 169
FRAME_W, FRAME_H = 1920.0, 1080.0
N_FEATURES = 134


def _interp_nan(a: np.ndarray) -> np.ndarray:
    """Linear interpolation along axis 0 with edge fill (pandas limit_direction='both')."""
    a = a.copy()
    T = a.shape[0]
    t = np.arange(T)
    for c in range(a.shape[1]):
        col = a[:, c]
        ok = ~np.isnan(col)
        if ok.all():
            continue
        if not ok.any():
            col[:] = 0.0
            continue
        col[~ok] = np.interp(t[~ok], t[ok], col[ok])
        a[:, c] = col
    return a


def frames_to_features(frames: Sequence[LandmarkFrame], swap_hands: bool = False) -> np.ndarray:
    """(T, 134) float32 in 1920x1080 pixel space, NaNs interpolated."""
    T = len(frames)
    pose = np.full((T, 25, 2), np.nan, dtype=np.float32)
    h1 = np.full((T, 21, 2), np.nan, dtype=np.float32)
    h2 = np.full((T, 21, 2), np.nan, dtype=np.float32)
    for i, f in enumerate(frames):
        if f.pose is not None:
            pose[i] = f.pose[:25, :2]
        lh, rh = (f.right_hand, f.left_hand) if swap_hands else (f.left_hand, f.right_hand)
        if lh is not None:
            h1[i] = lh[:, :2]
        if rh is not None:
            h2[i] = rh[:, :2]
    scale = np.array([FRAME_W, FRAME_H], dtype=np.float32)
    parts = []
    for arr in (pose, h1, h2):
        a = arr.reshape(T, -1)
        a = _interp_nan(a)
        a = a.reshape(T, -1, 2) * scale
        parts.append(a.reshape(T, -1))
    return np.concatenate(parts, axis=-1).astype(np.float32)


def pad_or_sample(feat: np.ndarray, max_len: int = MAX_FRAMES) -> np.ndarray:
    T = feat.shape[0]
    if T >= max_len:
        idx = np.linspace(0, T - 1, num=max_len).astype(int)
        return feat[idx]
    return np.pad(feat, ((0, max_len - T), (0, 0)), "constant")


def preprocess(frames: Sequence[LandmarkFrame], swap_hands: bool = False) -> np.ndarray | None:
    if len(frames) == 0 or not any(f.pose is not None for f in frames):
        return None
    return pad_or_sample(frames_to_features(frames, swap_hands))
