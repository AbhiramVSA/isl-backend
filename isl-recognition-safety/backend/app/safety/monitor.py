"""SafetyMonitor: fuses posture rules, the ST-GCN++ action head, the gesture FSM and
recognised safety-lexicon signs into an evidence-backed status with hysteresis.

Status levels: NORMAL < WATCH < WARNING < CRITICAL. Every active signal carries a value
(probability or seconds) and a reason string so the UI can show *why* an alert exists.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..config import settings
from ..landmarks.frame import LandmarkFrame
from ..models import stgcnpp as S
from ..models.registry import ModelRegistry
from .gesture import GestureFSM
from .posture import PostureAnalyzer

log = logging.getLogger(__name__)

SEVERITY = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}

# Recognised ISL glosses that count as safety evidence (keys are normalised HWGAT/INCLUDE labels)
SAFETY_LEXICON: dict[str, set[str]] = {
    "HELP": {"Help [VEB]", "Save", "Urgent", "Rescue"},
    "DANGER": {"Dangerous", "Attack", "Fire", "Accident", "Thief", "Gun", "Knife", "Kill/Murder", "Fear", "Beat", "Fall", "Emergency", "War"},
    "MEDICAL": {"Pain", "Hurt", "Sick", "Doctor", "Hospital", "Ambulance", "Medicine", "Blood", "Die [VEB]/Dead", "Death", "Patient", "Faint", "Jaundice", "Fever", "Heart Attack"},
    "CALL": {"Police", "Police Station", "Call", "Stop", "Need"},
}
LEXICON_WEIGHT = {"HELP": 1.0, "DANGER": 0.8, "MEDICAL": 0.6, "CALL": 0.5}


@dataclass
class Signal:
    key: str
    label: str
    value: float
    unit: str          # "p" | "s" | "n"
    active: bool
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "value": round(self.value, 3), "unit": self.unit,
                "active": self.active, "reason": self.reason}


@dataclass
class SafetyEvent:
    id: int
    t_ms: float
    severity: str
    key: str
    title: str
    evidence: list[str]
    cleared_t_ms: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "t_ms": self.t_ms, "severity": self.severity, "key": self.key, "title": self.title,
                "evidence": self.evidence, "cleared_t_ms": self.cleared_t_ms}


@dataclass
class ActionState:
    top: list[dict[str, Any]] = field(default_factory=list)
    valid: bool = False
    p_fall: float = 0.0
    p_stagger: float = 0.0
    p_medical: float = 0.0
    p_wave: float = 0.0
    reason: str = "action head idle"
    latency_ms: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {"top": [{"label": t["label"], "p": round(t["p"], 3)} for t in self.top[:3]], "valid": self.valid,
                "p_fall": round(self.p_fall, 3), "p_stagger": round(self.p_stagger, 3),
                "p_medical": round(self.p_medical, 3), "p_wave": round(self.p_wave, 3), "reason": self.reason,
                "latency_ms": self.latency_ms}


class SafetyMonitor:
    def __init__(self, registry: ModelRegistry):
        self.reg = registry
        self.posture = PostureAnalyzer()
        self.gesture = GestureFSM()
        self.reset()

    def reset(self) -> None:
        self.posture.reset()
        self.gesture.reset()
        self.action = ActionState()
        self._kp_hist: deque[tuple[float, np.ndarray, np.ndarray, int, int]] = deque()
        self._last_action_ms = -1e9
        self._votes: deque[dict[str, float]] = deque(maxlen=5)
        self.fall_track = "NORMAL"          # NORMAL | SUSPECT | FALLEN | RECOVERING
        self._fall_t: float | None = None
        self._fall_evidence: tuple[float, str] = (0.0, "")
        self._fall_reason = ""
        self.no_recovery_s = 0.0
        self._medical_since: float | None = None
        self._stagger_since: float | None = None
        self.medical_active = False
        self._lying_since: float | None = None
        self._upright_since: float | None = None
        self.distress = "NONE"              # NONE | WARNING | CRITICAL
        self._distress_t: float | None = None
        self.long_lie = False
        self.abnormal_motion = False
        self._lex_hits: deque[tuple[float, str, str, float]] = deque()   # (t, category, display, p)
        self.events: list[SafetyEvent] = []
        self._next_event = 1
        self._event_last: dict[str, float] = {}
        self.status = "NORMAL"
        self.score = 0.0
        self.signals: list[Signal] = []
        self.reasons: list[str] = []
        self._frozen_at: float | None = None

    # ------------------------------------------------------------------
    def note_gloss(self, gloss) -> None:
        if gloss.safety_lexicon and gloss.status != "unknown":
            self._lex_hits.append((gloss.t_end_ms / 1000.0, gloss.safety_lexicon, gloss.display, gloss.p))

    def process(self, f: LandmarkFrame) -> None:
        t = f.t_ms / 1000.0
        ps = self.posture.update(f)
        gs = self.gesture.update(f)
        # keypoint history for the action head
        xy, sc = f.coco17()
        self._kp_hist.append((f.t_ms, xy, sc, f.width, f.height))
        while self._kp_hist and f.t_ms - self._kp_hist[0][0] > 4000:
            self._kp_hist.popleft()
        if f.t_ms - self._last_action_ms >= settings.action_stride_ms:
            self._last_action_ms = f.t_ms
            self._run_action()
        self._update_tracks(t, ps, gs)
        self._compose(t, ps, gs, f.t_ms)

    # ------------------------------------------------------------------
    def _run_action(self) -> None:
        a = self.action
        if not self.reg.action:
            a.valid, a.reason = False, "ST-GCN++ head not loaded"
            return
        if len(self._kp_hist) < 20:
            a.valid, a.reason = False, "collecting frames"
            return
        frames = list(self._kp_hist)
        q = np.array([(sc > 0.3).mean() for _, _, sc, _, _ in frames])
        good = float((q >= settings.action_min_quality).mean())
        if good < 0.8:
            a.valid = False
            a.reason = f"keypoint quality too low for the action model ({good:.0%} of frames have ≥{settings.action_min_quality:.0%} joints visible; full body required)"
            self._votes.clear()
            a.p_fall = a.p_stagger = a.p_medical = a.p_wave = 0.0
            a.top = []
            return
        kp = np.stack([xy for _, xy, _, _, _ in frames])
        sc = np.stack([s for _, _, s, _, _ in frames])
        w, h = frames[-1][3], frames[-1][4]
        try:
            r = self.reg.action.predict(kp, sc, w, h)
        except Exception as e:  # noqa: BLE001
            a.valid, a.reason = False, f"action head error: {e}"
            return
        probs = r["probs"]
        vote = {"fall": float(probs[S.IDX_FALLING]), "stagger": float(probs[S.IDX_STAGGERING]),
                "medical": float(probs[S.IDX_MEDICAL].sum()), "wave": float(probs[S.IDX_WAVE].sum())}
        self._votes.append(vote)
        n = len(self._votes)
        a.p_fall = float(np.mean([v["fall"] for v in self._votes]))
        a.p_stagger = float(np.mean([v["stagger"] for v in self._votes]))
        a.p_medical = float(np.mean([v["medical"] for v in self._votes]))
        a.p_wave = float(np.mean([v["wave"] for v in self._votes]))
        a.top, a.valid, a.latency_ms = r["top"], True, r["latency_ms"]
        a.reason = f"ST-GCN++ on last {len(frames)} frames, {n}-vote mean"

    # ------------------------------------------------------------------
    def _update_tracks(self, t: float, ps, gs) -> None:
        a = self.action
        if not ps.person_present:
            # Timers freeze (a fallen person may be partly out of frame) and alerts are never cleared
            # here. Losing the pose right after a suspected fall is itself evidence: MediaPipe often
            # cannot track a person lying on the floor.
            if self.fall_track == "SUSPECT" and self._fall_t is not None and ps.absent_s >= 2.0 and t - self._fall_t <= 8.0:
                self.fall_track = "FALLEN"
                self._fall_reason = f"person no longer tracked {ps.absent_s:.0f} s after the drop"
            if self.fall_track == "FALLEN" and self._fall_t is not None:
                self.no_recovery_s = t - self._fall_t
            return
        # lying / upright durations
        if ps.lying:
            self._lying_since = self._lying_since or t
            self._upright_since = None
        else:
            self._lying_since = None
        if ps.upright:
            self._upright_since = self._upright_since or t
        else:
            self._upright_since = None
        lying_s = t - self._lying_since if self._lying_since else 0.0
        upright_s = t - self._upright_since if self._upright_since else 0.0

        fall_evidence = ps.sudden_drop or (a.valid and a.p_fall > 0.6)
        if fall_evidence:
            ev_p = max(a.p_fall if a.valid else 0.0, 0.6 if ps.sudden_drop else 0.0)
            self._fall_evidence = (ev_p, (f"ST-GCN++ falling p={a.p_fall:.2f}" if a.valid and a.p_fall > 0.6 else
                                          f"sudden drop: hip velocity {ps.hip_v:.1f} torso-lengths/s, head drop {ps.head_drop:.2f} in 1 s"))
        # medical cues must be sustained (a sign near the face is brief; holding one's head is not)
        if a.valid and a.p_medical > 0.5:
            self._medical_since = self._medical_since or t
        else:
            self._medical_since = None
        self.medical_active = self._medical_since is not None and t - self._medical_since >= 4.0
        if self.fall_track == "NORMAL":
            if fall_evidence:
                self.fall_track, self._fall_t = "SUSPECT", t
                self._fall_reason = ""
                self.no_recovery_s = 0.0
        elif self.fall_track == "SUSPECT":
            if lying_s >= 1.5:
                self.fall_track, self._fall_reason = "FALLEN", f"lying posture held {lying_s:.1f} s after the drop"
            elif a.valid and a.p_fall > 0.6 and lying_s >= 0.5:
                self.fall_track, self._fall_reason = "FALLEN", f"ST-GCN++ falling p={a.p_fall:.2f} with lying posture"
            elif t - (self._fall_t or t) > 5.0 and not fall_evidence and upright_s >= 1.0:
                self.fall_track = "NORMAL"
            elif t - (self._fall_t or t) > 8.0 and not fall_evidence:
                self.fall_track = "NORMAL"
        elif self.fall_track == "FALLEN":
            self.no_recovery_s = t - (self._fall_t or t)
            if upright_s >= 5.0 and (not a.valid or a.p_fall < 0.35):
                self.fall_track = "RECOVERING"
                self._fall_t = t
        elif self.fall_track == "RECOVERING":
            if t - (self._fall_t or t) > 10.0:
                self.fall_track = "NORMAL"
            elif fall_evidence:
                self.fall_track, self._fall_t = "SUSPECT", t

        self.long_lie = ps.lying and ps.immobile_s >= settings.long_lie_s
        # staggering from the action head must be sustained and corroborated by real motion
        if a.valid and a.p_stagger > 0.6 and ps.speed > 0.8:
            self._stagger_since = self._stagger_since or t
        else:
            self._stagger_since = None
        stagger_sustained = self._stagger_since is not None and t - self._stagger_since >= 3.0
        self.abnormal_motion = ps.frantic or stagger_sustained

        # distress: gesture cycles + recognised HELP signs
        cycles = self.gesture.recent_cycles
        while self._lex_hits and t - self._lex_hits[0][0] > 20.0:
            self._lex_hits.popleft()
        help_hits = [h for h in self._lex_hits if h[1] == "HELP"]
        if cycles >= 2 or (cycles >= 1 and (help_hits or gs.waving)) or len(help_hits) >= 2:
            self.distress, self._distress_t = "CRITICAL", t
        elif cycles >= 1 or help_hits or (gs.waving and (a.valid and a.p_wave > 0.3)):
            if self.distress != "CRITICAL":
                self.distress, self._distress_t = "WARNING", t
        if self._distress_t and t - self._distress_t > settings.event_cooldown_s:
            self.distress = "NONE"

    # ------------------------------------------------------------------
    def _compose(self, t: float, ps, gs, t_ms: float) -> None:
        a = self.action
        sig: list[Signal] = []
        reasons: list[str] = []
        score = 0.0

        # fall
        fall_active = self.fall_track in ("SUSPECT", "FALLEN")
        p_fall = a.p_fall if a.valid else 0.0
        ev_p, ev_txt = self._fall_evidence
        fall_val = max(p_fall, ev_p if fall_active else 0.0, 0.9 if self.fall_track == "FALLEN" else 0.0)
        fr = []
        if fall_active and ev_txt:
            fr.append(f"trigger: {ev_txt}")
        if a.valid:
            fr.append(f"ST-GCN++ falling p={a.p_fall:.2f} now ({len(self._votes)}-vote mean)")
        if self.fall_track == "FALLEN":
            fr.append(self._fall_reason or f"lying posture held (torso angle {ps.torso_angle_deg:.0f}°)")
        sig.append(Signal("fall", "Fall detected" if self.fall_track == "FALLEN" else "Possible fall", fall_val if fall_active else p_fall, "p",
                          fall_active, "; ".join(fr) or "no fall evidence"))
        no_recovery = self.fall_track == "FALLEN" and self.no_recovery_s >= settings.immobile_warn_s
        if self.fall_track == "FALLEN":
            reasons.append(f"Fall detected — {int(fall_val * 100)}%")
            score = max(score, 0.75)
            if no_recovery:
                reasons.append(f"No recovery — not upright for {int(self.no_recovery_s)} s after the fall")
                score = max(score, 0.85)
        elif self.fall_track == "SUSPECT":
            reasons.append(f"Possible fall — {int(fall_val * 100)}%")
            score = max(score, 0.45)

        # immobility / lying
        immobile_active = ps.immobile_s >= settings.immobile_warn_s and ps.person_present
        sig.append(Signal("immobility", "Prolonged immobility", ps.immobile_s, "s", immobile_active,
                          f"mean joint speed {ps.speed:.3f} torso-lengths/s for {ps.immobile_s:.0f} s"))
        if immobile_active:
            reasons.append(f"Prolonged immobility — {int(ps.immobile_s)} s")
            score = max(score, 0.35 if not ps.lying else 0.6)
        sig.append(Signal("lying", "Lying on the ground", 1.0 if ps.lying else 0.0, "p", ps.lying,
                          f"torso angle {ps.torso_angle_deg:.0f}°, bbox w/h {ps.bbox_ratio:.2f}"))
        if ps.lying and self.fall_track != "FALLEN":
            reasons.append(f"Lying posture — torso angle {ps.torso_angle_deg:.0f}°")
            score = max(score, 0.3)
        if self.long_lie:
            reasons.append(f"Long lie — immobile on the ground for {int(ps.immobile_s)} s")
            score = max(score, 0.85)

        # abnormal motion
        ab_val = max(ps.speed / 3.0 if ps.frantic else 0.0, a.p_stagger if a.valid else 0.0)
        sig.append(Signal("abnormal_motion", "Abnormal movement", min(ab_val, 1.0), "p", self.abnormal_motion,
                          (f"frantic: mean joint speed {ps.speed:.2f} torso-lengths/s" if ps.frantic else "") +
                          (f"; ST-GCN++ staggering p={a.p_stagger:.2f}" if a.valid and a.p_stagger > 0.2 else "") or "movement normal"))
        if self.abnormal_motion:
            reasons.append("Abnormal movement" + (f" — frantic motion {ps.speed:.1f} tl/s" if ps.frantic else f" — staggering {int(a.p_stagger * 100)}% sustained"))
            score = max(score, 0.4)

        # medical cues (sustained ≥ 4 s so that hand-to-face signs do not count)
        med_active = self.medical_active
        med_s = (t - self._medical_since) if self._medical_since else 0.0
        sig.append(Signal("medical", "Medical distress cue", a.p_medical if a.valid else 0.0, "p", med_active,
                          (f"ST-GCN++ headache/chest/back/neck/nausea/cough classes p={a.p_medical:.2f}, sustained {med_s:.0f} s (needs ≥4 s)"
                           if a.valid else "action head inactive")))
        if med_active:
            reasons.append(f"Medical distress cue — {int(a.p_medical * 100)}%")
            score = max(score, 0.4)

        # gestures
        cycles = self.gesture.recent_cycles
        sig.append(Signal("signal_for_help", "Signal-for-Help gesture", float(cycles), "n", cycles > 0,
                          f"palm→thumb tucked→fist cycles in last 8 s: {cycles}; current hand pose {gs.state}"))
        if cycles > 0:
            reasons.append(f"Signal-for-Help gesture — {cycles} cycle{'s' if cycles > 1 else ''}")
        sig.append(Signal("waving", "Waving for attention", 1.0 if gs.waving else 0.0, "p", gs.waving,
                          "raised hand oscillating sideways" if gs.waving else "no waving"))
        if gs.waving:
            reasons.append("Waving for attention")
            score = max(score, 0.3)

        # recognised safety signs
        recent = list(self._lex_hits)
        lex_val = max([h[3] * LEXICON_WEIGHT[h[1]] for h in recent], default=0.0)
        sig.append(Signal("safety_sign", "Safety-related sign recognised", lex_val, "p", bool(recent),
                          "; ".join(f"{h[2]} ({h[1]}) p={h[3]:.2f}" for h in recent[-4:]) or "none in last 20 s"))
        for h in recent[-3:]:
            reasons.append(f"{h[2].upper()} sign recognised ({h[1].lower()}) — {int(h[3] * 100)}%")
        if recent:
            score = max(score, 0.3 + 0.4 * lex_val)
        if self.distress == "CRITICAL":
            score = max(score, 0.9)
            reasons.append("Repeated distress signal")
        elif self.distress == "WARNING":
            score = max(score, 0.55)

        if not ps.person_present:
            sig.append(Signal("absent", "Person not tracked", ps.absent_s, "s", ps.absent_s > 3.0,
                              "no pose detected (out of frame, or lying in a pose the detector cannot track); safety timers frozen"))
            if ps.absent_s > 3.0 and (self.fall_track == "FALLEN" or self.distress != "NONE"):
                reasons.append(f"Person not tracked for {int(ps.absent_s)} s since the alert (possibly on the floor or out of frame)")

        # overall status
        if self.fall_track == "FALLEN" and (immobile_active or med_active or self.distress != "NONE" or no_recovery) or self.long_lie or self.distress == "CRITICAL":
            status = "CRITICAL"
            score = max(score, 0.9)
        elif self.fall_track == "FALLEN" or self.distress == "WARNING" or (immobile_active and ps.lying) or (self.abnormal_motion and med_active):
            status = "WARNING"
        elif self.fall_track == "SUSPECT" or immobile_active or self.abnormal_motion or med_active or recent or gs.waving or ps.lying:
            status = "WATCH"
        else:
            status = "NORMAL"
        self.status, self.score, self.signals, self.reasons = status, min(score, 1.0), sig, reasons
        self._log_events(t_ms, status, reasons)

    def _log_events(self, t_ms: float, status: str, reasons: list[str]) -> None:
        if status in ("WARNING", "CRITICAL"):
            key = f"{status}:{self.fall_track}:{self.distress}:{int(self.long_lie)}"
            last = self._event_last.get(key)
            if last is None or (t_ms - last) / 1000.0 > settings.event_cooldown_s:
                self._event_last[key] = t_ms
                title = ("Fall with no recovery" if self.fall_track == "FALLEN" and status == "CRITICAL" else
                         "Fall detected" if self.fall_track == "FALLEN" else
                         "Long lie" if self.long_lie else
                         "Distress signal" if self.distress != "NONE" else "Safety warning")
                self.events.append(SafetyEvent(self._next_event, t_ms, status, self.fall_track.lower() if self.fall_track != "NORMAL" else "distress",
                                               title, list(reasons)))
                self._next_event += 1
                self.events = self.events[-50:]
        elif self.events and self.events[-1].cleared_t_ms is None and status == "NORMAL":
            self.events[-1].cleared_t_ms = t_ms

    def state_json(self) -> dict[str, Any]:
        ps, gs = self.posture.st, self.gesture.st
        return {"status": self.status, "score": round(self.score, 2),
                "signals": [s.to_json() for s in self.signals],
                "tracks": {"fall": self.fall_track, "long_lie": self.long_lie, "distress": self.distress,
                           "abnormal_motion": self.abnormal_motion},
                "posture": ps.to_json(), "action": self.action.to_json(), "gesture": gs.to_json(),
                "reasons": list(self.reasons)}
