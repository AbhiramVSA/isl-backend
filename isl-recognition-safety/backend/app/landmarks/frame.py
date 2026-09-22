"""LandmarkFrame: the single data type both input paths produce.

Coordinates follow MediaPipe conventions: x, y normalised to [0, 1] of the
image (origin top-left), z relative depth, pose visibility in [0, 1].
"Left hand" is the *person's* left hand (MediaPipe handedness).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

# MediaPipe pose landmark indices used throughout
NOSE, L_EYE, R_EYE, L_EAR, R_EAR = 0, 2, 5, 7, 8
L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW, L_WRIST, R_WRIST = 11, 12, 13, 14, 15, 16
L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANKLE, R_ANKLE = 23, 24, 25, 26, 27, 28

# MediaPipe 33 -> COCO-17 index map
MP_TO_COCO17 = [NOSE, L_EYE, R_EYE, L_EAR, R_EAR, L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW,
                L_WRIST, R_WRIST, L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANKLE, R_ANKLE]


@dataclass
class LandmarkFrame:
    t_ms: float
    width: int
    height: int
    pose: np.ndarray | None          # (33, 4) x, y, z, visibility
    left_hand: np.ndarray | None     # (21, 3)
    right_hand: np.ndarray | None    # (21, 3)
    face_present: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    # ---- construction -----------------------------------------------------
    @classmethod
    def from_message(cls, msg: dict[str, Any]) -> "LandmarkFrame":
        def arr(v: Any, shape: tuple[int, int]) -> np.ndarray | None:
            if v is None:
                return None
            a = np.asarray(v, dtype=np.float32)
            if a.shape != shape:
                raise ValueError(f"expected shape {shape}, got {a.shape}")
            if not np.isfinite(a).all():
                raise ValueError("non-finite landmark values")
            return a

        return cls(
            t_ms=float(msg["t_ms"]),
            width=int(msg.get("width", 640)),
            height=int(msg.get("height", 480)),
            pose=arr(msg.get("pose"), (33, 4)),
            left_hand=arr(msg.get("left_hand"), (21, 3)),
            right_hand=arr(msg.get("right_hand"), (21, 3)),
            face_present=bool(msg.get("face", False)),
        )

    @classmethod
    def from_holistic_result(cls, result: Any, t_ms: float, width: int, height: int) -> "LandmarkFrame":
        """Build from a MediaPipe Tasks HolisticLandmarkerResult."""
        def lm_list(lms: Any, with_vis: bool) -> np.ndarray | None:
            if not lms:
                return None
            if with_vis:
                return np.array([[p.x, p.y, p.z, (p.visibility if p.visibility is not None else 1.0)] for p in lms],
                                dtype=np.float32)
            return np.array([[p.x, p.y, p.z] for p in lms], dtype=np.float32)

        return cls(
            t_ms=t_ms, width=width, height=height,
            pose=lm_list(result.pose_landmarks, True),
            left_hand=lm_list(result.left_hand_landmarks, False),
            right_hand=lm_list(result.right_hand_landmarks, False),
            face_present=bool(result.face_landmarks),
        )

    # ---- helpers ------------------------------------------------------------
    @property
    def has_pose(self) -> bool:
        return self.pose is not None

    @property
    def any_hand(self) -> bool:
        return self.left_hand is not None or self.right_hand is not None

    def shoulder_width(self) -> float | None:
        if self.pose is None:
            return None
        d = self.pose[L_SHOULDER, :2] - self.pose[R_SHOULDER, :2]
        w = float(np.hypot(d[0] * self.width, d[1] * self.height))
        return w if w > 1e-3 else None

    def to_json(self, include_z: bool = False) -> dict[str, Any]:
        def rounded(a: np.ndarray | None) -> list | None:
            return None if a is None else np.round(a, 4).tolist()
        return {
            "t_ms": self.t_ms, "width": self.width, "height": self.height,
            "pose": rounded(self.pose), "left_hand": rounded(self.left_hand),
            "right_hand": rounded(self.right_hand), "face": self.face_present,
        }

    def coco17(self) -> tuple[np.ndarray, np.ndarray]:
        """COCO-17 keypoints in pixel coords (17, 2) and scores (17,)."""
        if self.pose is None:
            return np.zeros((17, 2), np.float32), np.zeros(17, np.float32)
        p = self.pose[MP_TO_COCO17]
        xy = p[:, :2] * np.array([self.width, self.height], np.float32)
        return xy.astype(np.float32), p[:, 3].astype(np.float32)
