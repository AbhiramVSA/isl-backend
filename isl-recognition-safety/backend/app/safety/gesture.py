"""Distress-gesture finite-state machines on hand landmarks.

* Signal for Help (Canadian Women's Foundation, 2020): open palm facing camera ->
  thumb tucked into palm -> fingers fold down over the thumb. One full cycle = WARNING,
  two cycles within 8 s = CRITICAL.
* Help-waving: a hand raised above the shoulder oscillating sideways.
No learned model is involved; the geometry is evaluated on MediaPipe's 21 hand points in
pixel space. Thresholds were calibrated on real hand photos (MediaPipe's public test
images): finger tip/PIP distance ratio from the wrist is 1.23-1.43 when extended and
0.56-0.76 when curled; the thumb tip projected on the index-MCP -> pinky-MCP axis is
-0.8..-1.1 for an open palm with the thumb out and +0.19..+0.55 when the thumb is folded
across the palm.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from ..landmarks.frame import L_SHOULDER, L_WRIST, R_SHOULDER, R_WRIST, LandmarkFrame

TIP = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}
PIP = {"index": 6, "middle": 10, "ring": 14, "pinky": 18}
MCP = {"index": 5, "middle": 9, "ring": 13, "pinky": 17}

EXT_RATIO = 1.05          # tip farther from the wrist than the PIP joint by 5% => finger extended
THUMB_ACROSS = 0.10       # thumb tip past the index knuckle toward the pinky => thumb tucked/folded


def hand_features(h: np.ndarray, width: float = 1.0, height: float = 1.0) -> dict[str, float]:
    """Orientation-independent hand-shape features from 21 normalised landmarks."""
    p = h[:, :2] * np.array([width, height], np.float32)
    wrist = p[0]
    ext = {}
    for k in TIP:
        d_tip = np.linalg.norm(p[TIP[k]] - wrist)
        d_pip = np.linalg.norm(p[PIP[k]] - wrist) + 1e-6
        ext[k] = float(d_tip / d_pip)
    axis = p[MCP["pinky"]] - p[MCP["index"]]
    L = float(np.linalg.norm(axis)) + 1e-6
    across = float(np.dot(p[4] - p[MCP["index"]], axis / L) / L)
    return {"ext_" + k: v for k, v in ext.items()} | {"thumb_across": across}


def _hand_pose(h: np.ndarray, width: float = 1.0, height: float = 1.0) -> str:
    """Classify a single hand into OPEN_PALM / THUMB_TUCKED / FIST / OTHER."""
    f = hand_features(h, width, height)
    n_ext = sum(f["ext_" + k] > EXT_RATIO for k in TIP)
    tucked = f["thumb_across"] >= THUMB_ACROSS
    if n_ext == 4:
        return "THUMB_TUCKED" if tucked else "OPEN_PALM"
    if n_ext == 0 and f["thumb_across"] > -0.3:   # fingers curled, thumb not sticking out (not a thumbs-up)
        return "FIST"
    return "OTHER"


@dataclass
class GestureState:
    state: str = "NONE"       # current stable hand pose of the tracked hand
    stage: int = 0            # 0 none, 1 palm seen, 2 thumb tucked seen, 3 fist (cycle done)
    cycles: int = 0
    waving: bool = False
    last_cycle_t: float | None = None
    hand: str | None = None
    left: str = "NONE"        # live (unsmoothed) pose of each hand, for the UI
    right: str = "NONE"

    def to_json(self) -> dict:
        return {"state": self.state, "stage": self.stage, "cycles": self.cycles, "waving": self.waving,
                "hand": self.hand, "left": self.left, "right": self.right,
                "sequence": ["OPEN_PALM", "THUMB_TUCKED", "FIST"][: self.stage] if self.stage < 3 else ["OPEN_PALM", "THUMB_TUCKED", "FIST"]}


class GestureFSM:
    def __init__(self, hold_frames: int = 3, cycle_window_s: float = 3.0, repeat_window_s: float = 8.0):
        self.hold_frames, self.cycle_window_s, self.repeat_window_s = hold_frames, cycle_window_s, repeat_window_s
        self.reset()

    def reset(self) -> None:
        self.st = GestureState()
        self._counts = {"left": {}, "right": {}}
        self._stage_t: float = 0.0
        self._wave_hist: dict[str, deque] = {"left": deque(), "right": deque()}
        self._cycle_times: deque[float] = deque()

    def _stable(self, side: str, pose: str) -> str | None:
        c = self._counts[side]
        c[pose] = c.get(pose, 0) + 1
        for k in list(c):
            if k != pose:
                c[k] = 0
        return pose if c[pose] >= self.hold_frames else None

    def update(self, f: LandmarkFrame) -> GestureState:
        st = self.st
        t = f.t_ms / 1000.0
        st.waving = False
        progressed = False
        for side, hand, wrist_idx, sh_idx in (("left", f.left_hand, L_WRIST, L_SHOULDER),
                                              ("right", f.right_hand, R_WRIST, R_SHOULDER)):
            if hand is None:
                self._counts[side] = {}
                self._wave_hist[side].clear()
                setattr(st, side, "NONE")
                continue
            pose = _hand_pose(hand, f.width, f.height)
            setattr(st, side, pose)
            stable = self._stable(side, pose)
            raised = f.pose is not None and f.pose[wrist_idx, 1] < f.pose[sh_idx, 1] + 0.05
            # waving: wrist x oscillation while raised
            if raised and f.pose is not None:
                hist = self._wave_hist[side]
                sw = f.shoulder_width() or 100.0
                hist.append((t, f.pose[wrist_idx, 0] * f.width))
                while hist and t - hist[0][0] > 2.0:
                    hist.popleft()
                if len(hist) >= 8:
                    xs = np.array([x for _, x in hist])
                    dx = np.diff(xs)
                    dx = dx[np.abs(dx) > 0.5]
                    sign_changes = int(np.sum(np.diff(np.sign(dx)) != 0)) if len(dx) > 1 else 0
                    amp = float(xs.max() - xs.min())
                    if sign_changes >= 3 and amp > 0.3 * sw:
                        st.waving = True
            if stable is None:
                continue
            if st.hand not in (None, side) and t - self._stage_t < self.cycle_window_s:
                continue  # follow the hand that started the cycle
            # Signal-for-Help sequence (any visible hand; the signal is often made at chest height)
            if st.stage in (0, 3) and stable == "OPEN_PALM":
                st.stage, st.hand, self._stage_t = 1, side, t
                progressed = True
            elif st.stage == 1 and stable == "THUMB_TUCKED":
                st.stage, self._stage_t = 2, t
                progressed = True
            elif st.stage == 2 and stable == "FIST":
                st.stage, self._stage_t = 3, t
                st.cycles += 1
                st.last_cycle_t = t
                self._cycle_times.append(t)
                progressed = True
            if side == (st.hand or side):
                st.state = stable
        # timeouts
        if st.stage in (1, 2) and t - self._stage_t > self.cycle_window_s:
            st.stage, st.hand = 0, None
        while self._cycle_times and t - self._cycle_times[0] > self.repeat_window_s:
            self._cycle_times.popleft()
        st.cycles = len(self._cycle_times)
        if not progressed and st.stage == 3 and t - self._stage_t > self.cycle_window_s:
            st.stage, st.hand = 0, None
        if f.left_hand is None and f.right_hand is None:
            st.state = "NONE"
        return st

    @property
    def recent_cycles(self) -> int:
        return len(self._cycle_times)
