"""Geometric posture/motion features from pose landmarks (explainable, per-frame)."""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from ..landmarks.frame import (L_ANKLE, L_HIP, L_KNEE, L_SHOULDER, NOSE, R_ANKLE, R_HIP, R_KNEE,
                               R_SHOULDER, LandmarkFrame)


@dataclass
class PostureState:
    person_present: bool = False
    torso_angle_deg: float = 0.0     # 0 = vertical
    bbox_ratio: float = 0.0          # width / height of the visible-joint box
    speed: float = 0.0               # mean joint speed, torso-lengths / s (EMA)
    hip_v: float = 0.0               # vertical hip velocity, torso-lengths / s (+ = downward)
    head_drop: float = 0.0           # head height lost over the last second, torso-lengths
    lying: bool = False
    upright: bool = False
    sudden_drop: bool = False
    frantic: bool = False
    immobile_s: float = 0.0
    quality: float = 0.0             # fraction of COCO joints with visibility > 0.5
    legs_visible: bool = False
    absent_s: float = 0.0

    def to_json(self) -> dict:
        return {"person_present": self.person_present, "torso_angle_deg": round(self.torso_angle_deg, 1),
                "bbox_ratio": round(self.bbox_ratio, 2), "speed": round(self.speed, 3), "hip_v": round(self.hip_v, 2),
                "head_drop": round(self.head_drop, 2), "lying": self.lying, "upright": self.upright,
                "sudden_drop": self.sudden_drop, "frantic": self.frantic, "immobile_s": round(self.immobile_s, 1),
                "quality": round(self.quality, 2), "legs_visible": self.legs_visible, "absent_s": round(self.absent_s, 1)}


class PostureAnalyzer:
    def __init__(self, ema: float = 0.3, immobile_speed: float = 0.06, frantic_speed: float = 2.2,
                 drop_speed: float = 1.4, lying_angle: float = 60.0, upright_angle: float = 30.0):
        self.ema = ema
        self.immobile_speed, self.frantic_speed, self.drop_speed = immobile_speed, frantic_speed, drop_speed
        self.lying_angle, self.upright_angle = lying_angle, upright_angle
        self.reset()

    def reset(self) -> None:
        self.st = PostureState()
        self._prev: tuple[np.ndarray, np.ndarray, float] | None = None
        self._head_hist: deque[tuple[float, float]] = deque()  # (t, head_y_in_torso_units)
        self._still_since: float | None = None
        self._last_seen: float | None = None
        self._frantic_since: float | None = None
        self._torso_len = 1.0
        self._seen_frames = 0

    def update(self, f: LandmarkFrame) -> PostureState:
        st = self.st
        t = f.t_ms / 1000.0
        xy, sc = f.coco17()
        vis = sc > 0.5
        st.quality = float(vis.mean())
        present = f.pose is not None and vis[[5, 6]].all()  # both shoulders
        st.person_present = present
        if not present:
            if self._last_seen is not None:
                st.absent_s = t - self._last_seen
            st.sudden_drop = st.frantic = st.lying = st.upright = False
            st.speed = st.hip_v = st.head_drop = 0.0
            self._prev = None
            self._seen_frames = 0
            return st
        self._last_seen, st.absent_s = t, 0.0
        sh = (xy[5] + xy[6]) / 2
        hips_ok = vis[[11, 12]].all()
        hip = (xy[11] + xy[12]) / 2 if hips_ok else None
        if hip is not None:
            tl = float(np.linalg.norm(hip - sh))
            if tl > 1:
                self._torso_len = 0.8 * self._torso_len + 0.2 * tl
        else:
            sw = float(np.linalg.norm(xy[5] - xy[6]))
            if sw > 1:                                    # approx torso ~ 1.6 x shoulder width
                self._torso_len = 0.8 * self._torso_len + 0.2 * (1.6 * sw)
        tlen = max(self._torso_len, 1.0)
        st.legs_visible = bool(vis[[13, 14, 15, 16]].sum() >= 2)

        # torso angle vs vertical (image y grows downward)
        if hip is not None:
            v = hip - sh
            st.torso_angle_deg = abs(math.degrees(math.atan2(abs(v[0]), v[1]))) if abs(v[1]) > 1e-3 else 90.0
            if v[1] < 0:  # hips above shoulders -> upside down / lying
                st.torso_angle_deg = 180 - st.torso_angle_deg
        else:
            # shoulders-only estimate: a lying person's shoulder line is far from horizontal or head is near floor;
            # without hips we only flag lying via head drop + roll
            d = xy[5] - xy[6]
            roll = abs(math.degrees(math.atan2(d[1], d[0])))
            roll = min(roll, 180 - roll)
            st.torso_angle_deg = roll  # roll of the shoulder line as a proxy
        pts = xy[vis]
        w = float(pts[:, 0].max() - pts[:, 0].min())
        h = float(pts[:, 1].max() - pts[:, 1].min())
        st.bbox_ratio = w / h if h > 1 else 0.0

        # velocities
        if self._prev is not None:
            pxy, pvis, pt = self._prev
            dt = t - pt
            if dt > 0:
                both = vis & pvis
                if both.any():
                    sp = float(np.linalg.norm(xy[both] - pxy[both], axis=1).mean()) / tlen / dt
                    st.speed = (1 - self.ema) * st.speed + self.ema * min(sp, 20.0)
                if hip is not None and pvis[[11, 12]].all():
                    phip = (pxy[11] + pxy[12]) / 2
                    hv = float(hip[1] - phip[1]) / tlen / dt
                    st.hip_v = (1 - self.ema) * st.hip_v + self.ema * hv
                else:
                    psh = (pxy[5] + pxy[6]) / 2
                    hv = float(sh[1] - psh[1]) / tlen / dt
                    st.hip_v = (1 - self.ema) * st.hip_v + self.ema * hv
        self._prev = (xy.copy(), vis.copy(), t)

        # head drop over the last second (nose height relative to the image bottom, in torso units)
        head_y = float(xy[0][1]) / tlen if vis[0] else float(sh[1]) / tlen
        self._head_hist.append((t, head_y))
        while self._head_hist and t - self._head_hist[0][0] > 1.0:
            self._head_hist.popleft()
        st.head_drop = max(0.0, head_y - min(y for _, y in self._head_hist))

        # flags
        st.lying = st.torso_angle_deg > self.lying_angle and (st.bbox_ratio > 1.0 or not hips_ok)
        st.upright = st.torso_angle_deg < self.upright_angle and st.bbox_ratio < 1.0
        # sudden drop needs a warmed-up track (pose glitches on the first frames look like drops)
        self._seen_frames = getattr(self, "_seen_frames", 0) + 1
        st.sudden_drop = (self._seen_frames >= 10 and st.quality >= 0.5
                          and (st.hip_v > self.drop_speed or (st.head_drop > 0.6 and vis[0])))
        if st.speed > self.frantic_speed:
            self._frantic_since = self._frantic_since or t
        else:
            self._frantic_since = None
        st.frantic = self._frantic_since is not None and t - self._frantic_since >= 1.5
        if st.speed < self.immobile_speed:
            self._still_since = self._still_since or t
            st.immobile_s = t - self._still_since
        else:
            self._still_since = None
            st.immobile_s = 0.0
        return st
