"""Trace the safety monitor over a video: prints status/posture/action changes and the event log.

Usage: python scripts/safety_trace.py video1.mp4 [video2.mp4 ...]
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
logging.basicConfig(level=logging.WARNING)

from app.landmarks.holistic import HolisticExtractor  # noqa: E402
from app.models.registry import ModelRegistry  # noqa: E402
from app.pipeline import SessionPipeline  # noqa: E402


def main() -> None:
    reg = ModelRegistry()
    reg.load_all()
    for p in sys.argv[1:]:
        ex = HolisticExtractor(ROOT / "models" / "mediapipe" / "holistic_landmarker.task")
        pipe = SessionPipeline(reg, None, async_llm=False)
        cap = cv2.VideoCapture(p)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        i, last = 0, None
        print("==", p)
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            f = ex.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), i * 1000.0 / fps)
            s = pipe.process(f)
            sf = s["safety"]
            key = (sf["status"], sf["tracks"]["fall"], sf["posture"]["lying"], sf["action"]["valid"])
            if key != last or i % 30 == 0:
                ps, a = sf["posture"], sf["action"]
                act = ("/".join(f"{t['label'][:14]}:{t['p']}" for t in a["top"][:2]) if a["valid"] else a["reason"][:48])
                print(f"t={i / fps:5.2f}s {sf['status']:8s} fall={sf['tracks']['fall']:10s} lying={ps['lying']!s:5s} "
                      f"upright={ps['upright']!s:5s} angle={ps['torso_angle_deg']:5.1f} ratio={ps['bbox_ratio']:.2f} "
                      f"hip_v={ps['hip_v']:5.2f} drop={ps['head_drop']:.2f} speed={ps['speed']:.2f} "
                      f"immobile={ps['immobile_s']:.1f} q={ps['quality']:.2f} action={act} reasons={sf['reasons']}")
                last = key
            i += 1
        cap.release()
        ex.close()
        print("events:", [(e.t_ms, e.severity, e.title, e.evidence) for e in pipe.safety.events])


if __name__ == "__main__":
    main()
