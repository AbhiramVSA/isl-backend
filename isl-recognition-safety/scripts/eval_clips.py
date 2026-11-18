"""Stream INCLUDE-style clips (folder name = word) through the full pipeline and score the emitted glosses.

Usage: python scripts/eval_clips.py <root_dir> [--per-word N] [--max-width 960]
Expects <root>/**/<N. Word>/*.MOV|mp4. Prints per-clip glosses/sentences and a summary.
"""
from __future__ import annotations

import argparse
import glob
import logging
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
logging.basicConfig(level=logging.WARNING)

from app.landmarks.holistic import HolisticExtractor  # noqa: E402
from app.models.registry import ModelRegistry  # noqa: E402
from app.pipeline import SessionPipeline  # noqa: E402


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--per-word", type=int, default=2)
    ap.add_argument("--max-width", type=int, default=960)
    args = ap.parse_args()
    files = sorted(glob.glob(os.path.join(args.root, "**", "*.MOV"), recursive=True) +
                   glob.glob(os.path.join(args.root, "**", "*.mp4"), recursive=True))
    by_word: dict[str, list[str]] = defaultdict(list)
    for f in files:
        by_word[os.path.basename(os.path.dirname(f))].append(f)
    reg = ModelRegistry()
    reg.load_all()
    print({k: v.loaded for k, v in reg.infos.items()}, reg.device)
    hits = conf = unk = unc = n = 0
    for word, clips in sorted(by_word.items()):
        label = norm(word.split(". ", 1)[-1])
        for p in clips[: args.per_word]:
            ex = HolisticExtractor(ROOT / "models" / "mediapipe" / "holistic_landmarker.task")
            pipe = SessionPipeline(reg, None, async_llm=False)
            cap = cv2.VideoCapture(p)
            fps = cap.get(cv2.CAP_PROP_FPS) or 25
            i, t0 = 0, time.time()
            while True:
                ok, bgr = cap.read()
                if not ok:
                    break
                h, w = bgr.shape[:2]
                if w > args.max_width:
                    bgr = cv2.resize(bgr, (args.max_width, int(h * args.max_width / w)))
                pipe.process(ex.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), i * 1000.0 / fps))
                i += 1
            cap.release()
            ex.close()
            pipe.finish()
            snap = pipe.snapshot()
            if snap is None:
                print(f"{word:22s} no frames decoded ({p})")
                continue
            glosses = [g for s in snap["sentences"] for g in s["glosses"]] + snap["glosses"]
            gl = [(g["display"], g["status"], g["p"], g["heads"]) for g in glosses]
            hit = any(g["status"] != "unknown" and label in {norm(alt) for alt in re.split(r"[/(]", g["display"])}
                      for g in glosses)
            hits += hit
            n += 1
            conf += any(g["status"] == "confident" for g in glosses)
            unk += all(g["status"] == "unknown" for g in glosses) if glosses else 1
            unc += any(g["status"] == "uncertain" for g in glosses)
            print(f"{word:22s} {'HIT ' if hit else 'miss'} {i:3d}f {time.time() - t0:4.1f}s glosses={gl} -> {[s['final_text'] for s in snap['sentences']]}")
    print(f"\nclips={n} word-hit={hits}/{n} clips-with-confident-gloss={conf} clips-only-unknown={unk} clips-with-uncertain={unc}")


if __name__ == "__main__":
    main()
