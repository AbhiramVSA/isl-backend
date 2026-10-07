"""SigningGate: decides per frame whether the person is actively signing.

Signals (all computed from landmarks, no learned model):
  * hand presence (MediaPipe only returns a hand when it is visible)
  * motion energy: mean hand-landmark displacement, in shoulder-widths per second,
    median-filtered over 5 frames (the "optical flow from pose" idea of Moryossef et al. 2020)
  * a pause detector inside an active segment (short holds/transitions between signs)

State machine with hysteresis:
  IDLE  -> ACTIVE  when a hand is present and energy > on_thresh for `on_frames` frames
  ACTIVE -> IDLE   when hands are absent for `absent_frames` frames, or energy < off_thresh for `off_frames`
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from ..landmarks.frame import LandmarkFrame


@dataclass
class GateEvent:
    kind: str          # "segment_start" | "segment_end" | "pause"
    t_ms: float


@dataclass
class GateState:
    state: str = "IDLE"
    energy: float = 0.0
    segment_start_ms: float | None = None
    rest_since_ms: float | None = None
    hands_present: bool = False

    def to_json(self, now_ms: float) -> dict:
        return {"state": self.state, "energy": round(self.energy, 3),
                "segment_ms": int(now_ms - self.segment_start_ms) if self.segment_start_ms is not None else 0,
                "rest_ms": int(now_ms - self.rest_since_ms) if self.rest_since_ms is not None else 0}


class SigningGate:
    def __init__(self, on_thresh: float = 0.9, off_thresh: float = 0.35, pause_thresh: float = 0.4,
                 on_frames: int = 3, off_frames: int = 15, absent_frames: int = 12, pause_frames: int = 8,
                 min_pause_gap_ms: float = 1000.0):
        self.on_thresh, self.off_thresh, self.pause_thresh = on_thresh, off_thresh, pause_thresh
        self.on_frames, self.off_frames, self.absent_frames, self.pause_frames = on_frames, off_frames, absent_frames, pause_frames
        self.min_pause_gap_ms = min_pause_gap_ms
        self.reset()

    def reset(self) -> None:
        self.st = GateState()
        self._prev: LandmarkFrame | None = None
        self._energy_hist: deque[float] = deque(maxlen=5)
        self._sw = 120.0
        self._on_count = 0
        self._off_count = 0
        self._absent_count = 0
        self._pause_count = 0
        self._last_boundary_ms = -1e9
        self.st.rest_since_ms = None

    # ------------------------------------------------------------------
    def _hand_energy(self, prev: LandmarkFrame, cur: LandmarkFrame) -> float | None:
        dt = (cur.t_ms - prev.t_ms) / 1000.0
        if dt <= 0:
            return None
        scale = np.array([cur.width, cur.height], np.float32)
        disp = []
        for a, b in ((prev.left_hand, cur.left_hand), (prev.right_hand, cur.right_hand)):
            if a is not None and b is not None:
                disp.append(np.linalg.norm((b[:, :2] - a[:, :2]) * scale, axis=1).mean())
        if not disp:
            # fall back to wrist motion from pose when hands are not tracked
            if prev.pose is not None and cur.pose is not None:
                w = np.linalg.norm((cur.pose[[15, 16], :2] - prev.pose[[15, 16], :2]) * scale, axis=1)
                vis = np.minimum(cur.pose[[15, 16], 3], prev.pose[[15, 16], 3])
                if (vis > 0.5).any():
                    disp.append(float(w[vis > 0.5].mean()))
        if not disp:
            return None
        return float(np.mean(disp)) / self._sw / dt

    def update(self, f: LandmarkFrame) -> list[GateEvent]:
        events: list[GateEvent] = []
        sw = f.shoulder_width()
        if sw:
            self._sw = 0.8 * self._sw + 0.2 * sw
        hands = f.any_hand
        self.st.hands_present = hands
        e = self._hand_energy(self._prev, f) if self._prev is not None else None
        self._prev = f
        if e is not None:
            self._energy_hist.append(min(e, 20.0))
        energy = float(np.median(self._energy_hist)) if self._energy_hist else 0.0
        self.st.energy = energy

        if not hands:
            self._absent_count += 1
            self._on_count = 0
        else:
            self._absent_count = 0

        if self.st.state == "IDLE":
            if hands and energy > self.on_thresh:
                self._on_count += 1
            elif energy <= self.on_thresh:
                self._on_count = 0
            if self._on_count >= self.on_frames:
                self.st.state = "ACTIVE"
                self.st.segment_start_ms = f.t_ms - self.on_frames * 33.0
                self.st.rest_since_ms = None
                self._off_count = self._pause_count = 0
                self._last_boundary_ms = f.t_ms
                events.append(GateEvent("segment_start", self.st.segment_start_ms))
            elif self.st.rest_since_ms is None:
                self.st.rest_since_ms = f.t_ms
        else:  # ACTIVE
            if energy < self.off_thresh:
                self._off_count += 1
            else:
                self._off_count = 0
            if energy < self.pause_thresh:
                self._pause_count += 1
            else:
                self._pause_count = 0
            end = self._absent_count >= self.absent_frames or self._off_count >= self.off_frames
            if end:
                self.st.state = "IDLE"
                end_ms = f.t_ms - (self._absent_count if self._absent_count >= self.absent_frames else self._off_count) * 33.0 * 0.5
                events.append(GateEvent("segment_end", max(end_ms, self.st.segment_start_ms or end_ms)))
                self.st.segment_start_ms = None
                self.st.rest_since_ms = f.t_ms
                self._on_count = self._off_count = self._pause_count = 0
            elif (self._pause_count == self.pause_frames
                  and f.t_ms - self._last_boundary_ms >= self.min_pause_gap_ms):
                self._last_boundary_ms = f.t_ms
                events.append(GateEvent("pause", f.t_ms - self.pause_frames * 33.0 * 0.5))
        return events
