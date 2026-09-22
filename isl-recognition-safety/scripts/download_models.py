"""Download every pretrained checkpoint the app uses, with size verification.

Usage:  python scripts/download_models.py [--only hwgat,include,stgcnpp,mediapipe]

Sources (all verified 2026-09-14):
  * MediaPipe HolisticLandmarker  - storage.googleapis.com (Apache-2.0)
  * HWGAT FDMSE-ISL weights       - Google Drive (MIT), via gdown
  * INCLUDE transformer + labels  - Weights & Biases public files (MIT) + GitHub label map
  * ST-GCN++ NTU60 joint          - download.openmmlab.com (Apache-2.0, pyskl)
  * OpenHands SL-GCN INCLUDE      - GitHub release zip (Apache-2.0), converted to a plain state dict
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"

FILES = {
    "mediapipe": [
        ("mediapipe/holistic_landmarker.task",
         "https://storage.googleapis.com/mediapipe-models/holistic_landmarker/holistic_landmarker/float16/latest/holistic_landmarker.task",
         13_683_609),
    ],
    "include": [
        ("include/include_no_cnn_transformer_large.pth",
         "https://api.wandb.ai/files/abdur-ai4bharat/include-no-cnn/1nywb73r/augs_transformer.pth", 205_805_173),
        ("include/label_map_include.json",
         "https://raw.githubusercontent.com/AI4Bharat/INCLUDE/master/label_maps/label_map_include.json", None),
    ],
    "stgcnpp": [
        ("stgcnpp/stgcnpp_ntu60_xsub_hrnet_j.pth",
         "https://download.openmmlab.com/mmaction/pyskl/ckpt/stgcnpp/stgcnpp_ntu60_xsub_hrnet/j.pth", 5_854_105),
    ],
}
HWGAT_DRIVE_ID = "11DbOxiPmABieflBxGuV28org5Pm3ROsu"
OPENHANDS_SLGCN_URL = "https://github.com/AI4Bharat/OpenHands/releases/download/checkpoints_v1/include_slgcn.zip"
OPENHANDS_SLGCN_SIZE = 40_608_718


def fetch_slgcn() -> None:
    """OpenHands include_slgcn.zip (Lightning ckpt) -> plain state dict, no Lightning needed."""
    import pickle
    import types

    import torch

    d = MODELS / "openhands"
    d.mkdir(parents=True, exist_ok=True)
    out = d / "include_slgcn_state_dict.pt"
    classes = d / "include_slgcn_classes.json"
    if not classes.exists():
        raise RuntimeError("models/openhands/include_slgcn_classes.json is missing (it ships with the repo)")
    if out.exists():
        print("  ok      models/openhands/include_slgcn_state_dict.pt")
        return
    zpath = d / "include_slgcn.zip"
    fetch(OPENHANDS_SLGCN_URL, zpath, OPENHANDS_SLGCN_SIZE)
    with zipfile.ZipFile(zpath) as z:
        ckpts = [n for n in z.namelist() if n.endswith(".ckpt")]
        if not ckpts:
            raise RuntimeError("no .ckpt inside include_slgcn.zip")
        z.extract(ckpts[0], d)
        ckpt = d / ckpts[0]

    class _Stub:  # stands in for pytorch_lightning callback objects stored in the checkpoint
        def __init__(self, *a, **k): ...
        def __setstate__(self, s): ...

    class StubUnpickler(pickle.Unpickler):
        def find_class(self, module, name):
            try:
                import importlib
                return getattr(importlib.import_module(module), name)
            except Exception:  # noqa: BLE001
                return type(name, (_Stub,), {})

    pm = types.ModuleType("stubpickle")
    pm.Unpickler, pm.load = StubUnpickler, pickle.load
    ck = torch.load(str(ckpt), map_location="cpu", weights_only=False, pickle_module=pm)
    sd = {k[len("model."):]: v.clone().contiguous() for k, v in ck["state_dict"].items() if k.startswith("model.")}
    if len(sd) != 342:
        raise RuntimeError(f"unexpected SL-GCN state dict size {len(sd)} (expected 342 tensors)")
    torch.save(sd, out)
    print(f"  saved   models/openhands/include_slgcn_state_dict.pt ({len(sd)} tensors)")


def fetch(url: str, dest: Path, size: int | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and (size is None or dest.stat().st_size == size):
        print(f"  ok      {dest.relative_to(ROOT)}")
        return
    print(f"  fetch   {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "isl-app/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    got = dest.stat().st_size
    if size is not None and got != size:
        raise RuntimeError(f"{dest.name}: expected {size} bytes, got {got}")
    print(f"  saved   {dest.relative_to(ROOT)} ({got:,} bytes)")


def fetch_hwgat() -> None:
    d = MODELS / "hwgat"
    d.mkdir(parents=True, exist_ok=True)
    if (d / "model_best_loss.pt").exists() and (d / "class_map_FDMSE.csv").exists():
        print("  ok      models/hwgat/model_best_loss.pt")
        return
    try:
        import gdown
    except ImportError:
        sys.exit("pip install gdown  (needed for the HWGAT Google Drive download)")
    zpath = d / "best_model_and_FDMSE_class_map.zip"
    if not zpath.exists():
        print("  fetch   Google Drive id", HWGAT_DRIVE_ID)
        gdown.download(id=HWGAT_DRIVE_ID, output=str(zpath), quiet=False)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(d)
    if not (d / "model_best_loss.pt").exists():
        raise RuntimeError("HWGAT zip did not contain model_best_loss.pt")
    print("  saved   models/hwgat/model_best_loss.pt + class_map_FDMSE.csv")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="mediapipe,hwgat,include,slgcn,stgcnpp")
    args = ap.parse_args()
    wanted = {s.strip() for s in args.only.split(",")}
    failures = []
    for group in ("mediapipe", "include", "stgcnpp", "slgcn", "hwgat"):
        if group not in wanted:
            continue
        print(f"[{group}]")
        try:
            if group == "hwgat":
                fetch_hwgat()
            elif group == "slgcn":
                fetch_slgcn()
            else:
                for rel, url, size in FILES[group]:
                    fetch(url, MODELS / rel, size)
        except Exception as e:  # noqa: BLE001
            print(f"  FAILED  {group}: {e}")
            failures.append(group)
    if failures:
        sys.exit(f"some downloads failed: {failures}. The app still starts; those heads will be disabled.")
    print("all models present")


if __name__ == "__main__":
    main()
