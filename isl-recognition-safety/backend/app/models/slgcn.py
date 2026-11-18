"""Torch-only SL-GCN (Decoupled GCN) for INCLUDE isolated Indian Sign Language recognition.

Port of the ``decoupled-gcn`` encoder + ``fc`` decoder from AI4Bharat OpenHands
(Apache-2.0, https://github.com/AI4Bharat/OpenHands), which in turn adapts the SL-GCN of
Jiang et al. (CVPR21Chal-SLR).  Paper: Prem Selvaraj, Gokul NC, Pratyush Kumar, Mitesh
Khapra, "OpenHands: Making Sign Language Recognition Accessible with Pose-based Pretrained
Models across Languages", ACL 2022 (https://aclanthology.org/2022.acl-long.518).  The
released INCLUDE checkpoint (``include/sl_gcn/epoch=112-step=12203.ckpt``, 263 classes)
is reported at 93.5% top-1 on the INCLUDE test split.

Only inference is supported: DropGraph (spatial/temporal) is an identity outside training
and is therefore omitted; everything else follows ``openhands/models/encoder/graph/
decoupled_gcn.py`` and ``openhands/models/decoder/fc.py`` exactly, so the state dict
(with the Lightning ``model.`` prefix stripped) loads with ``strict=True``.

Input format, as determined from the OpenHands source:

* ``datasets/pipelines/generate_pose.py``: MediaPipe Holistic (legacy solution) landmarks
  are stored as ``[33 pose | 21 left hand | 21 right hand]`` = 75 points of *normalised*
  ``(x, y, z)`` in [0, 1] of the image; a missing component is all zeros.
* ``datasets/isolated/base.py``: ``pose_use_z_axis=False`` and
  ``pose_use_confidence_scores=False`` by default, so the tensor is ``(C=2, T, V)`` with
  only ``(x, y)``.  This matches the checkpoint (``data_bn`` has 2 x 27 = 54 features).
* ``datasets/pose_transforms.py``: ``PoseSelect(mediapipe_holistic_minimal_27)`` picks 27
  of the 75 points, then ``CenterAndScaleNormalize(shoulder_mediapipe_holistic_minimal_27,
  scale_factor=1)`` subtracts the clip-mean shoulder midpoint and divides by the clip-mean
  shoulder distance (clip level, not per frame).  There is no temporal subsampling in the
  ``sl_gcn`` config and the test dataloader uses ``batch_size=1`` (``collate_fn`` pads only
  up to the longest clip in the batch), so the model sees the full, variable-length clip.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Sequence

import numpy as np
import torch
import torch.nn as nn

from ..landmarks.frame import LandmarkFrame

NUM_CLASSES = 263
NUM_NODES = 27
IN_CHANNELS = 2

# PoseSelect.KEYPOINT_PRESETS["mediapipe_holistic_minimal_27"] over the 75-point layout
# [33 pose | 21 left hand | 21 right hand]:
#   0 nose, 1 L eye, 2 R eye, 3 L shoulder, 4 R shoulder, 5 L elbow, 6 R elbow,
#   7..16  left hand  (wrist, thumb tip, index mcp/tip, middle mcp/tip, ring mcp/tip, pinky mcp/tip),
#   17..26 right hand (same order).
POSE_INDEXES_27 = [0, 2, 5, 11, 12, 13, 14,
                   33, 37, 38, 41, 42, 45, 46, 49, 50, 53,
                   54, 58, 59, 62, 63, 66, 67, 70, 71, 74]
# CenterAndScaleNormalize.REFERENCE_PRESETS["shoulder_mediapipe_holistic_minimal_27"]
REFERENCE_POINTS = (3, 4)

# graph_args.inward_edges from the checkpoint's config.yaml
INWARD_EDGES = [(2, 0), (1, 0), (0, 3), (0, 4), (3, 5), (4, 6), (5, 7), (6, 17), (7, 8), (7, 9),
                (9, 10), (7, 11), (11, 12), (7, 13), (13, 14), (7, 15), (15, 16), (17, 18), (17, 19),
                (19, 20), (17, 21), (21, 22), (17, 23), (23, 24), (17, 25), (25, 26)]


# --------------------------------------------------------------------------------------
# Graph (openhands/models/encoder/graph/graph_utils.py, SpatialGraph)
# --------------------------------------------------------------------------------------
def _edge2mat(link, n: int) -> np.ndarray:
    A = np.zeros((n, n))
    for i, j in link:
        A[j, i] = 1
    return A


def _normalize_digraph(A: np.ndarray) -> np.ndarray:
    Dl = np.sum(A, 0)
    Dn = np.zeros_like(A)
    for i in range(A.shape[0]):
        if Dl[i] > 0:
            Dn[i, i] = Dl[i] ** (-1)
    return np.dot(A, Dn)


def spatial_graph(num_nodes: int = NUM_NODES, inward=INWARD_EDGES) -> np.ndarray:
    """(3, V, V) adjacency: identity, normalised inward, normalised outward."""
    outward = [(j, i) for i, j in inward]
    I = _edge2mat([(i, i) for i in range(num_nodes)], num_nodes)
    In = _normalize_digraph(_edge2mat(inward, num_nodes))
    Out = _normalize_digraph(_edge2mat(outward, num_nodes))
    return np.stack((I, In, Out))


# --------------------------------------------------------------------------------------
# Model (openhands/models/encoder/graph/decoupled_gcn.py)
# --------------------------------------------------------------------------------------
class TCNUnit(nn.Module):
    """Temporal conv + BN.  DropGraph is training-only and omitted here."""

    def __init__(self, cin: int, cout: int, kernel_size: int = 9, stride: int = 1):
        super().__init__()
        pad = (kernel_size - 1) // 2
        self.conv = nn.Conv2d(cin, cout, kernel_size=(kernel_size, 1), padding=(pad, 0), stride=(stride, 1))
        self.bn = nn.BatchNorm2d(cout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.bn(self.conv(x))


class DecoupledGCNUnit(nn.Module):
    def __init__(self, cin: int, cout: int, A: np.ndarray, groups: int, num_points: int, num_subset: int = 3):
        super().__init__()
        self.num_points = num_points
        self.out_channels = cout
        self.groups = groups
        self.num_subset = num_subset
        self.decoupled_A = nn.Parameter(
            torch.tensor(np.reshape(A, [3, 1, num_points, num_points]), dtype=torch.float32).repeat(1, groups, 1, 1))
        if cin != cout:
            self.down = nn.Sequential(nn.Conv2d(cin, cout, 1), nn.BatchNorm2d(cout))
        else:
            self.down = nn.Identity()
        self.bn0 = nn.BatchNorm2d(cout * num_subset)
        self.bn = nn.BatchNorm2d(cout)
        self.relu = nn.ReLU()
        self.linear_weight = nn.Parameter(torch.zeros(cin, cout * num_subset))
        self.linear_bias = nn.Parameter(torch.zeros(1, cout * num_subset, 1, 1))
        # upstream registers this as a non-trainable nn.Parameter; a buffer has the same state_dict key
        self.register_buffer("eye_list", torch.stack([torch.eye(num_points) for _ in range(cout)]))

    def norm(self, A: torch.Tensor) -> torch.Tensor:
        b, c, h, w = A.size()
        A = A.view(c, self.num_points, self.num_points)
        D_list = torch.sum(A, 1).view(c, 1, self.num_points)
        D_list_12 = (D_list + 0.001) ** (-1)
        D_12 = self.eye_list * D_list_12
        return torch.bmm(A, D_12).view(b, c, h, w)

    def forward(self, x0: torch.Tensor) -> torch.Tensor:
        learn_adj = self.decoupled_A.repeat(1, self.out_channels // self.groups, 1, 1)
        normed_adj = torch.cat([self.norm(learn_adj[k:k + 1]) for k in range(3)], 0)
        x = torch.einsum("nctw,cd->ndtw", x0, self.linear_weight).contiguous()
        x = x + self.linear_bias
        x = self.bn0(x)
        n, kc, t, v = x.size()
        x = x.view(n, self.num_subset, kc // self.num_subset, t, v)
        x = torch.einsum("nkctv,kcvw->nctw", x, normed_adj)
        x = self.bn(x)
        x = x + self.down(x0)
        return self.relu(x)


class DecoupledGCN_TCN_unit(nn.Module):
    """Decoupled GCN -> spatial/temporal/channel attention -> TCN, with residual."""

    def __init__(self, cin: int, cout: int, A: np.ndarray, groups: int, num_points: int,
                 stride: int = 1, residual: bool = True):
        super().__init__()
        num_joints = A.shape[-1]
        self.gcn1 = DecoupledGCNUnit(cin, cout, A, groups, num_points)
        self.tcn1 = TCNUnit(cout, cout, stride=stride)
        self.relu = nn.ReLU()
        self.sigmoid = nn.Sigmoid()
        # upstream: non-trainable nn.Parameter holding the summed (V, V) adjacency (only used by DropGraph)
        self.register_buffer("A", torch.tensor(np.sum(np.reshape(A.astype(np.float32), [3, num_points, num_points]), axis=0),
                                               dtype=torch.float32))
        if not residual:
            self.residual = None
        elif cin == cout and stride == 1:
            self.residual = nn.Identity()
        else:
            self.residual = TCNUnit(cin, cout, kernel_size=1, stride=stride)
        # temporal attention
        self.conv_ta = nn.Conv1d(cout, 1, 9, padding=4)
        # spatial attention
        ker_jpt = num_joints - 1 if not num_joints % 2 else num_joints
        self.conv_sa = nn.Conv1d(cout, 1, ker_jpt, padding=(ker_jpt - 1) // 2)
        # channel attention
        self.fc1c = nn.Linear(cout, cout // 2)
        self.fc2c = nn.Linear(cout // 2, cout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.gcn1(x)
        se = y.mean(-2)                                    # N C V
        y = y * self.sigmoid(self.conv_sa(se)).unsqueeze(-2) + y
        se = y.mean(-1)                                    # N C T
        y = y * self.sigmoid(self.conv_ta(se)).unsqueeze(-1) + y
        se = y.mean(-1).mean(-1)                           # N C
        se2 = self.sigmoid(self.fc2c(self.relu(self.fc1c(se))))
        y = y * se2.unsqueeze(-1).unsqueeze(-1) + y
        y = self.tcn1(y)
        if self.residual is not None:
            y = y + self.residual(x)
        return self.relu(y)


class DecoupledGCN(nn.Module):
    """ST-GCN backbone with decoupled GCN layers and self attention -> (N, 256) embedding."""

    def __init__(self, in_channels: int = IN_CHANNELS, num_points: int = NUM_NODES, inward_edges=INWARD_EDGES,
                 groups: int = 8, n_out_features: int = 256):
        super().__init__()
        A = spatial_graph(num_points, inward_edges)
        self.data_bn = nn.BatchNorm1d(in_channels * num_points)
        u = lambda cin, cout, **kw: DecoupledGCN_TCN_unit(cin, cout, A, groups, num_points, **kw)  # noqa: E731
        self.l1 = u(in_channels, 64, residual=False)
        self.l2 = u(64, 64)
        self.l3 = u(64, 64)
        self.l4 = u(64, 64)
        self.l5 = u(64, 128, stride=2)
        self.l6 = u(128, 128)
        self.l7 = u(128, 128)
        self.l8 = u(128, 256, stride=2)
        self.l9 = u(256, 256)
        self.l10 = u(256, n_out_features)
        self.n_out_features = n_out_features

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        N, C, T, V = x.size()
        x = x.permute(0, 3, 1, 2).contiguous().view(N, V * C, T)
        x = self.data_bn(x)
        x = x.view(N, V, C, T).permute(0, 2, 3, 1).contiguous()   # N C T V
        for layer in (self.l1, self.l2, self.l3, self.l4, self.l5, self.l6, self.l7, self.l8, self.l9, self.l10):
            x = layer(x)
        return x.reshape(N, x.size(1), -1).mean(2)


class FC(nn.Module):
    """openhands/models/decoder/fc.py with dropout_ratio=0, batch_norm=False."""

    def __init__(self, n_features: int, num_class: int, dropout_ratio: float = 0.0):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout_ratio)
        self.classifier = nn.Linear(n_features, num_class)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.dropout(x))


class SLGCN(nn.Module):
    """encoder (DecoupledGCN) + decoder (FC).  Input ``(N, 2, T, 27)`` -> logits ``(N, num_classes)``."""

    def __init__(self, num_classes: int = NUM_CLASSES):
        super().__init__()
        self.encoder = DecoupledGCN()
        self.decoder = FC(self.encoder.n_out_features, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.decoder(self.encoder(x))

    @classmethod
    def from_state_dict(cls, path: str | Path, num_classes: int = NUM_CLASSES, device: str | torch.device = "cpu") -> "SLGCN":
        """Load the plain state dict (Lightning ``model.`` prefix already stripped) strictly, eval mode."""
        sd = torch.load(str(path), map_location="cpu", weights_only=True)
        if any(k.startswith("model.") for k in sd):
            sd = {k[len("model."):]: v for k, v in sd.items()}
        model = cls(num_classes)
        model.load_state_dict(sd, strict=True)
        return model.to(device).eval()


# --------------------------------------------------------------------------------------
# Preprocessing (OpenHands test pipeline: PoseSelect 27 -> CenterAndScaleNormalize)
# --------------------------------------------------------------------------------------
def frames_to_kp75(frames: Sequence[LandmarkFrame]) -> np.ndarray | None:
    """LandmarkFrames -> (T, 75, 2) normalised (x, y) in OpenHands' [pose | left | right] layout.

    Frames without a pose are skipped (the holistic run failed for them); a missing hand is
    zeros, exactly as ``generate_pose.py`` stores an undetected component.
    """
    out = []
    for f in frames:
        if f.pose is None:
            continue
        kp = np.zeros((75, 2), np.float32)
        kp[:33] = f.pose[:, :2]
        if f.left_hand is not None:
            kp[33:54] = f.left_hand[:, :2]
        if f.right_hand is not None:
            kp[54:75] = f.right_hand[:, :2]
        out.append(kp)
    if not out:
        return None
    return np.stack(out)


def center_and_scale_normalize(x: np.ndarray, ref: tuple[int, int] = REFERENCE_POINTS, scale_factor: float = 1.0) -> np.ndarray:
    """Clip-level CenterAndScaleNormalize on (T, V, C): subtract mean shoulder midpoint, divide by mean shoulder distance."""
    p1, p2 = x[:, ref[0], :], x[:, ref[1], :]
    center = np.mean((p1 + p2) / 2, axis=0)
    mean_dist = np.mean(np.sqrt(((p1 - p2) ** 2).sum(-1)))
    if mean_dist == 0:                                     # upstream: scale=inf -> "do not normalize"
        return x
    return (x - center) * (scale_factor / mean_dist)


def preprocess(frames: Sequence[LandmarkFrame], emulate_aspect: float | None = None) -> np.ndarray | None:
    """LandmarkFrames -> (2, T, 27) float32 model input (add a batch dim), or None if no usable pose.

    ``emulate_aspect``: if given (e.g. ``16 / 9``, the INCLUDE recording aspect), the
    normalised ``y`` is rescaled so the skeleton has the same proportions it would have in a
    frame of that aspect ratio.  The upstream pipeline does *not* do this (it feeds raw
    normalised coordinates), so the default ``None`` is the faithful choice; the option only
    matters when the live source has a different aspect ratio than the training videos.
    """
    if len(frames) == 0:
        return None
    kp = frames_to_kp75(frames)
    if kp is None:
        return None
    if emulate_aspect is not None:
        wh = [(f.width, f.height) for f in frames if f.pose is not None]
        src_aspect = np.array([w / h for w, h in wh], np.float32)[:, None]
        kp = kp.copy()
        kp[:, :, 1] *= src_aspect / emulate_aspect
    x = kp[:, POSE_INDEXES_27, :]                          # (T, 27, 2)
    x = center_and_scale_normalize(x)
    return np.ascontiguousarray(x.transpose(2, 0, 1), dtype=np.float32)   # (C, T, V)


# --------------------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------------------
DEFAULT_MODELS_DIR = Path(__file__).resolve().parents[3] / "models" / "openhands"
DEFAULT_STATE_DICT = DEFAULT_MODELS_DIR / "include_slgcn_state_dict.pt"
DEFAULT_CLASSES = DEFAULT_MODELS_DIR / "include_slgcn_classes.json"

_DISPLAY_OVERRIDES = {
    "GoodMorning": "Good morning", "Goodafternoon": "Good afternoon", "Goodevening": "Good evening",
    "Goodnight": "Good night", "Thankyou": "Thank you", "Howareyou": "How are you",
    "StreetorRoad": "Street or road", "StoreorShop": "Store or shop", "TrainStation": "Train station",
    "trainticket": "Train ticket", "biglarge": "Big / large", "smalllittle": "Small / little",
    "you(plural)": "You (plural)", "Race(ethnicity)": "Race (ethnicity)", "Second(Number)": "Second (number)",
    "T-Shirt": "T-shirt",
}


def display_label(raw: str) -> str:
    """'1.Dog' -> 'Dog', 'Ex.Monsoon' -> 'Monsoon', 'Second(Number)' -> 'Second (number)'."""
    s = re.sub(r"^(\d+|Ex)\.", "", raw).strip()
    if s in _DISPLAY_OVERRIDES:
        return _DISPLAY_OVERRIDES[s]
    return s[:1].upper() + s[1:]


def load_labels(path: str | Path = DEFAULT_CLASSES) -> tuple[list[str], list[str]]:
    """Return (LABELS, DISPLAY_LABELS); index i = class i (OpenHands INCLUDEDataset.read_glosses order)."""
    labels = json.loads(Path(path).read_text(encoding="utf-8"))
    if len(labels) != NUM_CLASSES:
        raise ValueError(f"expected {NUM_CLASSES} INCLUDE classes, got {len(labels)}")
    return list(labels), [display_label(s) for s in labels]


LABELS, DISPLAY_LABELS = load_labels() if DEFAULT_CLASSES.exists() else ([], [])
