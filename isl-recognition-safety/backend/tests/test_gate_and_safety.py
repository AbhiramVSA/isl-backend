import numpy as np
import pytest

from app.models.registry import ModelRegistry
from app.recognition.gate import SigningGate
from app.safety.gesture import GestureFSM, _hand_pose
from app.safety.monitor import SafetyMonitor
from app.safety.posture import PostureAnalyzer


class DummyRegistry:
    """Registry stand-in with no action head (rules only)."""
    action = None
    hwgat = None
    include = None

    class device:
        type = "cpu"


def test_gate_activates_on_hand_motion_and_ends_on_rest(frame_factory):
    gate = SigningGate()
    states = []
    t = 0.0
    # 20 frames still -> IDLE
    for i in range(20):
        gate.update(frame_factory(t)); t += 33
        states.append(gate.st.state)
    assert all(s == "IDLE" for s in states)
    # moving hands (large displacement per frame) -> ACTIVE
    for i in range(15):
        gate.update(frame_factory(t, hand_offset=(0.05 * np.sin(i), 0.05 * np.cos(i)))); t += 33
    assert gate.st.state == "ACTIVE"
    assert gate.st.segment_start_ms is not None
    # still again -> IDLE with a segment_end event
    events = []
    for i in range(30):
        events += gate.update(frame_factory(t)); t += 33
    assert gate.st.state == "IDLE"
    assert any(e.kind == "segment_end" for e in events)


def test_gate_pause_event_inside_long_segment(frame_factory):
    gate = SigningGate()
    t = 0.0
    evs = []
    for i in range(40):                       # ~1.3 s of signing
        evs += gate.update(frame_factory(t, hand_offset=(0.05 * np.sin(i), 0.05 * np.cos(i)))); t += 33
    for i in range(14):                       # ~0.45 s hold (shorter than the 0.5 s end-of-segment rest)
        evs += gate.update(frame_factory(t, hand_offset=(0.05 * np.sin(40), 0.05 * np.cos(40)))); t += 33
    for i in range(20):
        evs += gate.update(frame_factory(t, hand_offset=(0.05 * np.sin(i), 0.05 * np.cos(i)))); t += 33
    kinds = [e.kind for e in evs]
    assert "segment_start" in kinds and "pause" in kinds and "segment_end" not in kinds


def test_posture_lying_and_immobility(frame_factory):
    pa = PostureAnalyzer()
    t = 0.0
    for _ in range(40):
        st = pa.update(frame_factory(t)); t += 33
    assert st.upright and not st.lying
    for _ in range(40):
        st = pa.update(frame_factory(t, torso_angle_deg=80, center=(0.5, 0.7))); t += 33
    assert st.lying and not st.upright
    assert st.immobile_s > 0.5


def test_safety_fall_sequence_reaches_warning_then_critical(frame_factory):
    mon = SafetyMonitor(DummyRegistry())
    t = 0.0
    for _ in range(30):                       # standing still
        mon.process(frame_factory(t)); t += 33
    assert mon.status == "NORMAL"
    # rapid drop: body centre moves down fast while rotating to horizontal over ~0.4 s
    for i in range(12):
        k = i / 11
        mon.process(frame_factory(t, torso_angle_deg=85 * k, center=(0.5, 0.45 + 0.3 * k), scale=0.18)); t += 33
    # lying still for 4 s
    for _ in range(120):
        mon.process(frame_factory(t, torso_angle_deg=85, center=(0.5, 0.75))); t += 33
    assert mon.fall_track == "FALLEN"
    assert mon.status in ("WARNING", "CRITICAL")
    assert any("fall" in r.lower() for r in mon.reasons)
    # immobile for 12 more seconds -> CRITICAL with immobility evidence
    for _ in range(360):
        mon.process(frame_factory(t, torso_angle_deg=85, center=(0.5, 0.75))); t += 33
    assert mon.status == "CRITICAL"
    assert any("immobility" in r.lower() for r in mon.reasons)
    assert mon.events and mon.events[-1].severity in ("WARNING", "CRITICAL")


def test_safety_normal_signing_does_not_alert(frame_factory):
    mon = SafetyMonitor(DummyRegistry())
    t = 0.0
    for i in range(300):
        mon.process(frame_factory(t, hand_offset=(0.04 * np.sin(i / 3), 0.04 * np.cos(i / 3)))); t += 33
    assert mon.status == "NORMAL", mon.reasons


def _hand(ext, thumb_tucked):
    """Build a hand: fingers extended (tip beyond pip) or curled; thumb tucked into palm or extended."""
    h = np.zeros((21, 3), np.float32)
    h[0] = (0.5, 0.6, 0)
    xs = [0.44, 0.48, 0.52, 0.56]
    for f, x in enumerate(xs):
        base = 5 + f * 4
        h[base] = (x, 0.5, 0)                       # MCP
        h[base + 1] = (x, 0.45, 0)                  # PIP
        h[base + 2] = (x, 0.41 if ext else 0.50, 0)  # DIP
        h[base + 3] = (x, 0.37 if ext else 0.53, 0)  # TIP
    h[1] = (0.42, 0.58, 0); h[2] = (0.39, 0.55, 0); h[3] = (0.37, 0.52, 0)
    h[4] = (0.5, 0.52, 0) if thumb_tucked else (0.34, 0.48, 0)
    return h


def test_hand_pose_classifier():
    assert _hand_pose(_hand(True, False)) == "OPEN_PALM"
    assert _hand_pose(_hand(True, True)) == "THUMB_TUCKED"
    assert _hand_pose(_hand(False, True)) == "FIST"


def test_signal_for_help_fsm(frame_factory):
    fsm = GestureFSM()
    t = 0.0
    seq = [(True, False)] * 6 + [(True, True)] * 6 + [(False, True)] * 6
    for ext, tuck in seq:
        f = frame_factory(t)
        f.right_hand = _hand(ext, tuck)
        f.pose[16, 1] = f.pose[12, 1] - 0.1   # raised wrist
        fsm.update(f); t += 33
    assert fsm.recent_cycles == 1
