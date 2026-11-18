import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.landmarks.frame import LandmarkFrame  # noqa: E402


def make_frame(t_ms: float, width: int = 640, height: int = 480, torso_angle_deg: float = 0.0,
               center: tuple[float, float] = (0.5, 0.45), scale: float = 0.18, hands: bool = True,
               hand_offset: tuple[float, float] = (0.0, 0.0), legs: bool = True) -> LandmarkFrame:
    """Synthetic standing person; torso_angle_deg rotates the body about the shoulder midpoint."""
    a = np.deg2rad(torso_angle_deg)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    cx, cy = center
    # body template in units of `scale` (x right, y down), shoulders at origin
    tpl = {0: (0.0, -0.9), 2: (-0.1, -1.0), 5: (0.1, -1.0), 7: (-0.2, -0.95), 8: (0.2, -0.95),
           11: (-0.5, 0.0), 12: (0.5, 0.0), 13: (-0.7, 0.8), 14: (0.7, 0.8), 15: (-0.6, 1.5), 16: (0.6, 1.5),
           23: (-0.35, 1.6), 24: (0.35, 1.6), 25: (-0.4, 2.8), 26: (0.4, 2.8), 27: (-0.4, 4.0), 28: (0.4, 4.0)}
    pose = np.zeros((33, 4), np.float32)
    for i in range(33):
        v = np.array(tpl.get(i, (0.0, 0.5)))
        v = rot @ v
        pose[i, :2] = (cx + v[0] * scale, cy + v[1] * scale)
        pose[i, 3] = 0.95 if (i in tpl and (legs or i < 23)) else 0.05
    def hand(center_xy):
        h = np.zeros((21, 3), np.float32)
        for j in range(21):
            h[j, 0] = center_xy[0] + (j % 5) * 0.01
            h[j, 1] = center_xy[1] - (j // 5) * 0.012
        return h
    lh = rh = None
    if hands:
        lh = hand((pose[15, 0] + hand_offset[0], pose[15, 1] + hand_offset[1]))
        rh = hand((pose[16, 0] + hand_offset[0], pose[16, 1] + hand_offset[1]))
    return LandmarkFrame(t_ms=t_ms, width=width, height=height, pose=pose, left_hand=lh, right_hand=rh, face_present=True)


@pytest.fixture
def frame_factory():
    return make_frame
