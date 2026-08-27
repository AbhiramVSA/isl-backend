from __future__ import annotations

import argparse
import platform
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
import torch
import torch.nn as nn


HOLISTIC_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "holistic_landmarker/holistic_landmarker/float16/1/"
    "holistic_landmarker.task"
)

POSE_COUNT = 33
HAND_COUNT = 21


# ---------------------------------------------------------------------
# PyTorch model — must match Notebook 2 exactly
# ---------------------------------------------------------------------


class LearnedPos(nn.Module):
    def __init__(self, n: int, d: int, drop: float):
        super().__init__()
        self.pos = nn.Parameter(torch.zeros(1, n, d))
        nn.init.trunc_normal_(self.pos, std=0.02)
        self.drop = nn.Dropout(drop)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.drop(x + self.pos[:, : x.size(1)])


class StreamEncoder(nn.Module):
    def __init__(
        self,
        inp: int,
        d: int,
        nhead: int,
        layers: int,
        ff: int,
        drop: float,
        nframes: int,
    ):
        super().__init__()
        self.proj = nn.Sequential(
            nn.Linear(inp, d),
            nn.LayerNorm(d),
        )
        self.pos = LearnedPos(nframes, d, drop)

        layer = nn.TransformerEncoderLayer(
            d_model=d,
            nhead=nhead,
            dim_feedforward=ff,
            dropout=drop,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        # Nested tensors are only an optional optimization. The training
        # architecture used norm_first=True, so disable the incompatible
        # nested-tensor fast path explicitly to avoid the warning.
        self.enc = nn.TransformerEncoder(
            layer,
            num_layers=layers,
            norm=nn.LayerNorm(d),
            enable_nested_tensor=False,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.enc(self.pos(self.proj(x)))


class LandmarkEncoder(nn.Module):
    def __init__(
        self,
        num_frames: int,
        d_model: int,
        nhead: int,
        num_stream_layers: int,
        num_temporal_layers: int,
        dim_feedforward: int,
        dropout: float,
    ):
        super().__init__()
        self.num_frames = num_frames
        self.embedding_dim = d_model

        self.left_encoder = StreamEncoder(
            63,
            d_model,
            nhead,
            num_stream_layers,
            dim_feedforward,
            dropout,
            num_frames,
        )
        self.right_encoder = StreamEncoder(
            63,
            d_model,
            nhead,
            num_stream_layers,
            dim_feedforward,
            dropout,
            num_frames,
        )
        self.pose_encoder = StreamEncoder(
            132,
            d_model,
            nhead,
            num_stream_layers,
            dim_feedforward,
            dropout,
            num_frames,
        )

        self.fusion = nn.Sequential(
            nn.Linear(3 * d_model, d_model),
            nn.GELU(),
            nn.LayerNorm(d_model),
            nn.Dropout(dropout),
        )

        self.cls = nn.Parameter(torch.zeros(1, 1, d_model))
        nn.init.trunc_normal_(self.cls, std=0.02)

        self.pos = LearnedPos(num_frames + 1, d_model, dropout)

        layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.temporal = nn.TransformerEncoder(
            layer,
            num_layers=num_temporal_layers,
            norm=nn.LayerNorm(d_model),
            enable_nested_tensor=False,
        )
        self.norm = nn.LayerNorm(d_model)

    def forward_tokens(
        self,
        left: torch.Tensor,
        right: torch.Tensor,
        pose: torch.Tensor,
    ) -> torch.Tensor:
        b = left.size(0)

        l = self.left_encoder(left.reshape(b, self.num_frames, 63))
        r = self.right_encoder(right.reshape(b, self.num_frames, 63))
        p = self.pose_encoder(pose.reshape(b, self.num_frames, 132))

        x = self.fusion(torch.cat([l, r, p], dim=-1))
        x = torch.cat([self.cls.expand(b, -1, -1), x], dim=1)
        return self.temporal(self.pos(x))

    def forward(
        self,
        left: torch.Tensor,
        right: torch.Tensor,
        pose: torch.Tensor,
    ) -> torch.Tensor:
        return self.norm(self.forward_tokens(left, right, pose)[:, 0])


class SignClassifier(nn.Module):
    def __init__(
        self,
        encoder: LandmarkEncoder,
        nclasses: int,
        drop: float,
    ):
        super().__init__()
        self.encoder = encoder
        self.head = nn.Sequential(
            nn.Dropout(drop),
            nn.Linear(encoder.embedding_dim, nclasses),
        )

    def forward(
        self,
        left: torch.Tensor,
        right: torch.Tensor,
        pose: torch.Tensor,
    ) -> torch.Tensor:
        return self.head(self.encoder(left, right, pose))


# ---------------------------------------------------------------------
# Checkpoint + device
# ---------------------------------------------------------------------


def choose_device(requested: str) -> torch.device:
    if requested != "auto":
        return torch.device(requested)

    if torch.cuda.is_available():
        return torch.device("cuda")

    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")

    return torch.device("cpu")


def safe_torch_load(path: Path):
    # Notebook 2 saves tensors + primitive Python containers, so
    # weights_only=True is sufficient on recent PyTorch versions.
    try:
        return torch.load(
            path,
            map_location="cpu",
            weights_only=True,
        )
    except TypeError:
        # Compatibility with older PyTorch releases that do not expose
        # the weights_only keyword.
        return torch.load(path, map_location="cpu")


def load_classifier(checkpoint_path: Path, device: torch.device):
    cp = safe_torch_load(checkpoint_path)

    required = {
        "model_state_dict",
        "model_config",
        "preprocessing_config",
        "num_classes",
        "label_mapping",
    }
    missing = required - set(cp)
    if missing:
        raise RuntimeError(f"Checkpoint is missing required fields: {sorted(missing)}")

    cfg = cp["model_config"]
    model = SignClassifier(
        LandmarkEncoder(**cfg),
        int(cp["num_classes"]),
        float(cfg["dropout"]),
    )
    model.load_state_dict(cp["model_state_dict"], strict=True)
    model.to(device).eval()

    label_mapping = cp["label_mapping"]
    raw_idx = label_mapping.get("idx_to_label", {})
    idx_to_label = {int(k): str(v) for k, v in raw_idx.items()}

    if len(idx_to_label) != int(cp["num_classes"]):
        # Recover from label_to_idx if needed.
        l2i = label_mapping.get("label_to_idx", {})
        idx_to_label = {int(v): str(k) for k, v in l2i.items()}

    if len(idx_to_label) != int(cp["num_classes"]):
        raise RuntimeError("Could not reconstruct idx_to_label from checkpoint.")

    return model, cp, idx_to_label


# ---------------------------------------------------------------------
# Exact Notebook 2 preprocessing
# ---------------------------------------------------------------------


def clean_array(a: np.ndarray) -> np.ndarray:
    return np.nan_to_num(
        np.asarray(a, dtype=np.float32),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )


def origin_scale(
    pose: np.ndarray,
    pmask: np.ndarray,
    *,
    left_shoulder: int,
    right_shoulder: int,
    visibility_threshold: float,
    eps: float,
):
    xyz = pose[..., :3]
    vis = pose[..., 3]

    ls = xyz[:, left_shoulder]
    rs = xyz[:, right_shoulder]

    scales = np.linalg.norm(ls - rs, axis=1)
    origins = (ls + rs) / 2.0

    good = (
        pmask
        & (vis[:, left_shoulder] >= visibility_threshold)
        & (vis[:, right_shoulder] >= visibility_threshold)
        & np.isfinite(scales)
        & (scales > eps)
    )

    if good.any():
        fallback_origin = np.median(
            origins[good],
            axis=0,
        ).astype(np.float32)
        fallback_scale = float(np.median(scales[good]))
    else:
        points = []

        for i in range(len(pose)):
            if pmask[i]:
                q = xyz[i][vis[i] >= visibility_threshold]
                if len(q):
                    points.append(q)

        if points:
            q = np.concatenate(points)
            fallback_origin = np.median(
                q,
                axis=0,
            ).astype(np.float32)

            extent = np.percentile(q[:, :2], 90, axis=0) - np.percentile(
                q[:, :2], 10, axis=0
            )
            fallback_scale = float(np.linalg.norm(extent))
        else:
            fallback_origin = np.zeros(3, np.float32)
            fallback_scale = 1.0

    if not np.isfinite(fallback_scale) or fallback_scale <= eps:
        fallback_scale = 1.0

    origins[~good] = fallback_origin
    scales[~good] = fallback_scale

    return (
        origins.astype(np.float32),
        np.clip(scales, eps, None).astype(np.float32),
    )


def normalize_stream(
    a: np.ndarray,
    mask: np.ndarray,
    origins: np.ndarray,
    scales: np.ndarray,
    is_pose: bool = False,
) -> np.ndarray:
    a = clean_array(a)
    out = np.zeros_like(a, dtype=np.float32)
    idx = np.where(mask)[0]

    if len(idx) == 0:
        return out

    norm = (a[..., :3] - origins[:, None, :]) / scales[:, None, None]

    out[idx, :, :3] = norm[idx]

    if is_pose:
        out[idx, :, 3] = np.clip(a[idx, :, 3], 0.0, 1.0)

    return out


def fill_missing(
    a: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray:
    t = len(a)
    idx = np.flatnonzero(mask)

    if len(idx) == 0:
        return np.zeros_like(a, dtype=np.float32)

    if len(idx) == 1:
        return np.repeat(
            a[idx],
            t,
            axis=0,
        ).astype(np.float32)

    flat = a.reshape(t, -1)
    out = np.empty_like(flat)
    target = np.arange(t, dtype=np.float32)

    for j in range(flat.shape[1]):
        out[:, j] = np.interp(
            target,
            idx.astype(np.float32),
            flat[idx, j],
        )

    return out.reshape(a.shape)


def resample(
    a: np.ndarray,
    n: int,
) -> np.ndarray:
    t = len(a)

    if t <= 0:
        raise ValueError("empty sequence")

    if t == n:
        return a.astype(np.float32, copy=True)

    if t == 1:
        return np.repeat(
            a,
            n,
            axis=0,
        ).astype(np.float32)

    sx = np.linspace(0, 1, t, dtype=np.float32)
    tx = np.linspace(0, 1, n, dtype=np.float32)

    flat = a.reshape(t, -1)
    out = np.empty((n, flat.shape[1]), np.float32)

    for j in range(flat.shape[1]):
        out[:, j] = np.interp(tx, sx, flat[:, j])

    return out.reshape((n,) + a.shape[1:])


def preprocess(
    left: np.ndarray,
    right: np.ndarray,
    pose: np.ndarray,
    left_mask: np.ndarray,
    right_mask: np.ndarray,
    pose_mask: np.ndarray,
    cfg: dict,
):
    left = clean_array(left)
    right = clean_array(right)
    pose = clean_array(pose)

    if not (len(left) == len(right) == len(pose)) or len(pose) == 0:
        raise ValueError("invalid sequence lengths")

    num_frames = int(cfg["num_frames"])
    left_shoulder = int(cfg.get("left_shoulder_index", 11))
    right_shoulder = int(cfg.get("right_shoulder_index", 12))
    visibility_threshold = float(cfg.get("pose_visibility_threshold", 0.25))
    eps = float(cfg.get("normalization_eps", 1e-6))

    origins, scales = origin_scale(
        pose,
        pose_mask,
        left_shoulder=left_shoulder,
        right_shoulder=right_shoulder,
        visibility_threshold=visibility_threshold,
        eps=eps,
    )

    left = normalize_stream(
        left,
        left_mask,
        origins,
        scales,
    )
    right = normalize_stream(
        right,
        right_mask,
        origins,
        scales,
    )
    pose = normalize_stream(
        pose,
        pose_mask,
        origins,
        scales,
        is_pose=True,
    )

    if cfg.get("interpolate_missing_stream_frames", True):
        left = fill_missing(left, left_mask)
        right = fill_missing(right, right_mask)
        pose = fill_missing(pose, pose_mask)

    return (
        resample(left, num_frames),
        resample(right, num_frames),
        resample(pose, num_frames),
    )


# ---------------------------------------------------------------------
# MediaPipe Holistic — same representation as Notebook 1
# ---------------------------------------------------------------------


def ensure_holistic_model(path: Path) -> Path:
    if path.exists() and path.stat().st_size > 1_000_000:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)

    print("Downloading MediaPipe Holistic model...")
    try:
        urllib.request.urlretrieve(HOLISTIC_MODEL_URL, path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise RuntimeError(
            "Could not download holistic_landmarker.task.\n"
            f"URL: {HOLISTIC_MODEL_URL}\n"
            "Download it manually and pass --holistic-model PATH.\n"
            f"Original error: {exc}"
        ) from exc

    if path.stat().st_size <= 1_000_000:
        path.unlink(missing_ok=True)
        raise RuntimeError("Downloaded Holistic model is unexpectedly small.")

    print(f"MediaPipe model saved to: {path}")
    return path


def make_landmarker(model_path: Path):
    BaseOptions = mp.tasks.BaseOptions
    RunningMode = mp.tasks.vision.RunningMode
    HolisticLandmarker = mp.tasks.vision.HolisticLandmarker
    HolisticLandmarkerOptions = mp.tasks.vision.HolisticLandmarkerOptions

    options = HolisticLandmarkerOptions(
        base_options=BaseOptions(
            model_asset_path=str(model_path),
            delegate=BaseOptions.Delegate.CPU,
        ),
        running_mode=RunningMode.VIDEO,
        min_face_detection_confidence=0.5,
        min_face_landmarks_confidence=0.5,
        min_pose_detection_confidence=0.5,
        min_pose_landmarks_confidence=0.5,
        min_hand_landmarks_confidence=0.5,
        output_face_blendshapes=False,
        output_segmentation_mask=False,
    )

    return HolisticLandmarker.create_from_options(options)


def landmarks_to_array(
    landmarks,
    expected_count: int,
    *,
    with_visibility: bool,
):
    width = 4 if with_visibility else 3
    arr = np.zeros(
        (expected_count, width),
        dtype=np.float32,
    )

    if not landmarks:
        return arr, False

    for i, lm in enumerate(landmarks[:expected_count]):
        arr[i, 0] = float(getattr(lm, "x", 0.0) or 0.0)
        arr[i, 1] = float(getattr(lm, "y", 0.0) or 0.0)
        arr[i, 2] = float(getattr(lm, "z", 0.0) or 0.0)

        if with_visibility:
            visibility = getattr(lm, "visibility", None)
            arr[i, 3] = float(visibility) if visibility is not None else 1.0

    return arr, True


class SignRecorder:
    def __init__(
        self,
        holistic_model: Path,
        camera_fps: float,
    ):
        self.holistic_model = holistic_model
        self.camera_fps = (
            camera_fps
            if np.isfinite(camera_fps) and 1.0 <= camera_fps <= 240.0
            else 30.0
        )
        self.reset()

    def reset(self):
        if getattr(self, "landmarker", None) is not None:
            self.landmarker.close()

        self.landmarker = make_landmarker(self.holistic_model)

        self.pose = []
        self.left = []
        self.right = []

        self.pose_mask = []
        self.left_mask = []
        self.right_mask = []

        self.frame_index = 0

    def add_frame(self, frame_bgr: np.ndarray):
        rgb = cv2.cvtColor(
            frame_bgr,
            cv2.COLOR_BGR2RGB,
        )
        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(rgb),
        )

        timestamp_ms = int(round(self.frame_index * 1000.0 / self.camera_fps))

        result = self.landmarker.detect_for_video(
            mp_image,
            timestamp_ms,
        )

        pose, pose_ok = landmarks_to_array(
            result.pose_landmarks,
            POSE_COUNT,
            with_visibility=True,
        )
        left, left_ok = landmarks_to_array(
            result.left_hand_landmarks,
            HAND_COUNT,
            with_visibility=False,
        )
        right, right_ok = landmarks_to_array(
            result.right_hand_landmarks,
            HAND_COUNT,
            with_visibility=False,
        )

        self.pose.append(pose)
        self.left.append(left)
        self.right.append(right)

        self.pose_mask.append(pose_ok)
        self.left_mask.append(left_ok)
        self.right_mask.append(right_ok)

        self.frame_index += 1

    def arrays(self):
        if not self.pose:
            raise RuntimeError("No frames were recorded.")

        return (
            np.stack(self.left).astype(
                np.float32,
                copy=False,
            ),
            np.stack(self.right).astype(
                np.float32,
                copy=False,
            ),
            np.stack(self.pose).astype(
                np.float32,
                copy=False,
            ),
            np.asarray(
                self.left_mask,
                dtype=np.bool_,
            ),
            np.asarray(
                self.right_mask,
                dtype=np.bool_,
            ),
            np.asarray(
                self.pose_mask,
                dtype=np.bool_,
            ),
        )

    def close(self):
        if getattr(self, "landmarker", None) is not None:
            self.landmarker.close()
            self.landmarker = None


# ---------------------------------------------------------------------
# Prediction/UI
# ---------------------------------------------------------------------


def pretty_label(label: str) -> str:
    # class_key from Notebook 2 is typically "category::label".
    if "::" in label:
        return label.split("::", 1)[1]
    return label


@torch.inference_mode()
def predict(
    model: nn.Module,
    device: torch.device,
    idx_to_label: dict[int, str],
    preproc_cfg: dict,
    arrays,
    topk: int,
):
    (
        left,
        right,
        pose,
        left_mask,
        right_mask,
        pose_mask,
    ) = arrays

    left, right, pose = preprocess(
        left,
        right,
        pose,
        left_mask,
        right_mask,
        pose_mask,
        preproc_cfg,
    )

    left_t = torch.from_numpy(np.ascontiguousarray(left)).unsqueeze(0).to(device)

    right_t = torch.from_numpy(np.ascontiguousarray(right)).unsqueeze(0).to(device)

    pose_t = torch.from_numpy(np.ascontiguousarray(pose)).unsqueeze(0).to(device)

    logits = model(
        left_t,
        right_t,
        pose_t,
    )
    probs = torch.softmax(
        logits.float(),
        dim=1,
    )[0]

    k = min(
        int(topk),
        probs.numel(),
    )
    values, indices = torch.topk(probs, k)

    output = []
    for prob, idx in zip(
        values.cpu().tolist(),
        indices.cpu().tolist(),
    ):
        output.append(
            (
                idx_to_label[int(idx)],
                float(prob),
            )
        )

    stats = {
        "frames": int(len(left_mask)),
        "pose_rate": float(pose_mask.mean()),
        "left_rate": float(left_mask.mean()),
        "right_rate": float(right_mask.mean()),
    }

    return output, stats


def draw_status(
    frame: np.ndarray,
    *,
    recording: bool,
    elapsed: float,
    seconds: float,
    last_prediction,
    device: torch.device,
):
    view = cv2.flip(frame, 1)
    h, w = view.shape[:2]

    overlay = view.copy()
    cv2.rectangle(
        overlay,
        (0, 0),
        (w, 135),
        (0, 0, 0),
        -1,
    )
    cv2.addWeighted(
        overlay,
        0.55,
        view,
        0.45,
        0,
        view,
    )

    if recording:
        title = f"RECORDING {elapsed:.1f}/{seconds:.1f}s"
        color = (0, 0, 255)
    else:
        title = "Press SPACE to record one sign"
        color = (255, 255, 255)

    cv2.putText(
        view,
        title,
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        color,
        2,
        cv2.LINE_AA,
    )

    if last_prediction:
        label, confidence = last_prediction[0]
        cv2.putText(
            view,
            f"Prediction: {pretty_label(label)}",
            (20, 72),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (80, 255, 80),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            view,
            f"Confidence: {confidence * 100:.1f}%",
            (20, 104),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (80, 255, 80),
            2,
            cv2.LINE_AA,
        )

    cv2.putText(
        view,
        f"PyTorch: {device} | Q/ESC: quit",
        (20, h - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )

    return view


def open_camera(index: int):
    # Default backend is the most portable option across macOS/Linux/Windows.
    cap = cv2.VideoCapture(index)

    if not cap.isOpened():
        raise RuntimeError(
            f"Could not open camera {index}. "
            "Try --camera 1 if you have multiple cameras."
        )

    return cap


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Test the trained INCLUDE landmark classifier from a local webcam."
        )
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("best_classifier.pt"),
        help="Path to best_classifier.pt",
    )
    parser.add_argument(
        "--holistic-model",
        type=Path,
        default=Path(".models/holistic_landmarker.task"),
        help=("MediaPipe Holistic .task file. Downloaded automatically if missing."),
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="OpenCV camera index (default: 0)",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=3.0,
        help=("Maximum recording duration for one isolated sign (default: 3.0)"),
    )
    parser.add_argument(
        "--topk",
        type=int,
        default=5,
        help="Number of predictions to print (default: 5)",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help=("PyTorch device: auto, cpu, cuda, mps, cuda:0, etc."),
    )
    args = parser.parse_args()

    if not args.checkpoint.exists():
        raise FileNotFoundError(
            f"Checkpoint not found: {args.checkpoint}\n"
            "Download best_classifier.pt from Kaggle and "
            "put it beside local_test.py, or pass "
            "--checkpoint /path/to/best_classifier.pt"
        )

    if args.seconds <= 0:
        raise ValueError("--seconds must be > 0")

    device = choose_device(args.device)
    print("Python:", sys.version.split()[0])
    print("Platform:", platform.platform())
    print("PyTorch:", torch.__version__)
    print("MediaPipe:", mp.__version__)
    print("Device:", device)

    model, checkpoint, idx_to_label = load_classifier(
        args.checkpoint,
        device,
    )

    preproc_cfg = checkpoint["preprocessing_config"]
    print("Classes:", checkpoint["num_classes"])
    print(
        "Model trained epoch:",
        checkpoint.get("epoch", "unknown"),
    )
    print(
        "Validation metrics:",
        checkpoint.get("validation_metrics", {}),
    )
    print(
        "Expected temporal frames:",
        preproc_cfg["num_frames"],
    )

    holistic_model = ensure_holistic_model(args.holistic_model)

    cap = open_camera(args.camera)

    fps = float(cap.get(cv2.CAP_PROP_FPS))
    if not np.isfinite(fps) or fps < 1 or fps > 240:
        fps = 30.0

    print("Camera FPS reported:", fps)
    print()
    print("Controls:")
    print("  SPACE : start/finish recording one isolated sign")
    print("  Q/ESC : quit")
    print()
    print(
        "Important: perform ONE sign per recording. "
        "This is an isolated-sign classifier, not sentence translation."
    )

    recorder = None
    recording = False
    started = 0.0
    last_prediction = None

    try:
        while True:
            ok, frame = cap.read()

            if not ok or frame is None:
                print("Camera frame read failed.")
                break

            now = time.monotonic()

            if recording:
                try:
                    recorder.add_frame(frame)
                except Exception as exc:
                    print(
                        "\nMediaPipe failed on frame:",
                        repr(exc),
                    )

                elapsed = now - started

                if elapsed >= args.seconds:
                    recording = False
                    print("\nProcessing recorded sign...")

                    try:
                        arrays = recorder.arrays()
                        predictions, stats = predict(
                            model,
                            device,
                            idx_to_label,
                            preproc_cfg,
                            arrays,
                            args.topk,
                        )
                        last_prediction = predictions

                        print(
                            f"Frames={stats['frames']} | "
                            f"pose={stats['pose_rate']:.1%} | "
                            f"left={stats['left_rate']:.1%} | "
                            f"right={stats['right_rate']:.1%}"
                        )
                        print("Top predictions:")
                        for rank, (label, prob) in enumerate(
                            predictions,
                            start=1,
                        ):
                            print(
                                f"  {rank}. "
                                f"{pretty_label(label):25s} "
                                f"{prob * 100:6.2f}% "
                                f"[{label}]"
                            )

                        if stats["pose_rate"] < 0.5 or (
                            stats["left_rate"] < 0.1 and stats["right_rate"] < 0.1
                        ):
                            print(
                                "WARNING: landmark detection coverage "
                                "was low; prediction may be unreliable."
                            )

                    except Exception as exc:
                        print(
                            "Prediction failed:",
                            repr(exc),
                        )

                    finally:
                        recorder.close()
                        recorder = None

            elapsed = now - started if recording else 0.0

            display_frame = draw_status(
                frame,
                recording=recording,
                elapsed=elapsed,
                seconds=args.seconds,
                last_prediction=last_prediction,
                device=device,
            )

            cv2.imshow(
                "ISL Local Test",
                display_frame,
            )

            key = cv2.waitKey(1) & 0xFF

            if key in (27, ord("q"), ord("Q")):
                break

            if key == 32:  # SPACE
                if not recording:
                    recorder = SignRecorder(
                        holistic_model,
                        fps,
                    )
                    recording = True
                    started = time.monotonic()
                    last_prediction = None
                    print(f"\nRecording for up to {args.seconds:.1f}s...")

                else:
                    # Finish early if SPACE is pressed again.
                    recording = False
                    print("\nRecording stopped manually. Processing...")

                    try:
                        arrays = recorder.arrays()
                        predictions, stats = predict(
                            model,
                            device,
                            idx_to_label,
                            preproc_cfg,
                            arrays,
                            args.topk,
                        )
                        last_prediction = predictions

                        print(
                            f"Frames={stats['frames']} | "
                            f"pose={stats['pose_rate']:.1%} | "
                            f"left={stats['left_rate']:.1%} | "
                            f"right={stats['right_rate']:.1%}"
                        )
                        print("Top predictions:")
                        for rank, (label, prob) in enumerate(
                            predictions,
                            start=1,
                        ):
                            print(
                                f"  {rank}. "
                                f"{pretty_label(label):25s} "
                                f"{prob * 100:6.2f}% "
                                f"[{label}]"
                            )

                    except Exception as exc:
                        print(
                            "Prediction failed:",
                            repr(exc),
                        )

                    finally:
                        recorder.close()
                        recorder = None

    finally:
        if recorder is not None:
            recorder.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
