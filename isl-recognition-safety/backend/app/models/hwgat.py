"""HWGAT — Hierarchical Windowed Graph Attention Network for isolated ISL recognition.

Ported from https://github.com/suvajit-patra/sl-hwgat-demo (MIT, Patra et al. 2024/2025,
"Hierarchical Windowed Graph Attention Network and a Large Scale Dataset for Isolated
Indian Sign Language Recognition"). Weights: FDMSE-ISL, 2,002 classes.

The model code is kept structurally identical to upstream so the published
``model_best_loss.pt`` loads with ``strict=True``. Preprocessing reproduces the demo's
``test_transform`` exactly (pixel scaling -> 29-keypoint select -> hand correction ->
nose/shoulder normalisation -> 192-frame temporal sample -> 4-window assembly).
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import torch
import torch.nn as nn
from scipy import interpolate

from ..landmarks.frame import (L_ELBOW, L_EYE, L_SHOULDER, L_WRIST, NOSE, R_ELBOW, R_EYE,
                               R_SHOULDER, R_WRIST, LandmarkFrame)

SRC_LEN = 192
NUM_CLASSES = 2002

# ---------------------------------------------------------------------------
# Model (verbatim structure from upstream models/HWGATE.py)
# ---------------------------------------------------------------------------


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, dropout: float, max_len: int = 5000):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2) * -(math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0).unsqueeze(2)
        self.register_buffer("pe", pe)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.dropout(x + self.pe[:, : x.size(1)])


def window_partition(x: torch.Tensor, window_size: int, temporal_patch_size: int) -> torch.Tensor:
    W, TP = window_size, temporal_patch_size
    B, F, K, ED = x.shape
    f, nW = F // TP, K // W
    x = x.reshape(B, f, TP, nW, W, ED).transpose(2, 3).contiguous()
    return x.view(B * f * nW, TP * W, ED)


def window_reverse(x: torch.Tensor, window_size: int, temporal_patch_size: int,
                   temporal_dim: int, num_kp: int) -> torch.Tensor:
    W, TP = window_size, temporal_patch_size
    F, K = temporal_dim, num_kp
    B_f_nW, W_TP, ED = x.shape
    f, nW = F // TP, K // W
    B = int(B_f_nW / (f * nW))
    x = x.reshape(B, f, nW, TP, W, ED).transpose(2, 3).contiguous()
    return x.view(B, F, K, ED)


class TemporalMerging(nn.Module):
    def __init__(self, dim: int, temporal_patch_size: int):
        super().__init__()
        self.dim = dim
        self.temporal_patch_size = temporal_patch_size

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        TP = self.temporal_patch_size
        B, F, K, ED = x.shape
        f = F // TP
        x = x.reshape(B, f, TP, K, ED).transpose(2, 3).contiguous()
        return x.reshape(B, f, K, -1).contiguous()


class MSA(nn.Module):
    def __init__(self, dim: int, num_heads: int, adj_mat: torch.Tensor | None = None,
                 attn_drop: float = 0.0, proj_drop: float = 0.0):
        super().__init__()
        self.dim = dim
        self.num_heads = num_heads
        head_dim = dim // num_heads
        self.scale = head_dim ** -0.5
        self.adj_mat = adj_mat
        self.qkv = nn.Linear(dim, dim * 3)
        self.attn_drop = nn.Dropout(attn_drop)
        self.proj = nn.Linear(dim, dim)
        self.proj_drop = nn.Dropout(proj_drop)
        self.softmax = nn.Softmax(dim=-1)

    def forward(self, x: torch.Tensor, B: int, f: int, nW: int, mask: torch.Tensor | None = None) -> torch.Tensor:
        B_f_nW, W_TP, ED = x.shape
        qkv = self.qkv(x).reshape(B_f_nW, W_TP, 3, self.num_heads, ED // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        q = q * self.scale
        attn = q @ k.transpose(-2, -1)
        if mask is not None:
            attn = attn.view(B, f * nW, *attn.shape[1:]) * mask.unsqueeze(1).unsqueeze(0)
            attn = attn.view(B * f * nW, *attn.shape[2:])
        if self.adj_mat is not None:
            adj = self.adj_mat.to(attn.device, attn.dtype)
            attn = attn.view(B, f * nW, *attn.shape[1:]) * adj.unsqueeze(1)
            attn = attn.view(B * f * nW, *attn.shape[2:])
        attn = attn.masked_fill(attn == 0, float(-10000))
        attn = self.softmax(attn)
        attn = self.attn_drop(attn)
        x = (attn @ v).transpose(1, 2).reshape(B_f_nW, W_TP, ED)
        return self.proj_drop(self.proj(x))


class FeedForward(nn.Module):
    def __init__(self, in_features: int, hidden_features: int, drop: float = 0.0):
        super().__init__()
        self.fc1 = nn.Linear(in_features, hidden_features)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(hidden_features, in_features)
        self.drop = nn.Dropout(drop)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.drop(self.fc2(self.drop(self.act(self.fc1(x)))))


class PartAttentionBlock(nn.Module):
    def __init__(self, dim: int, num_kps: int, num_heads: int, window_size: int, temporal_patch_size: int,
                 temporal_dim: int, shift_size: int, adj_mat: torch.Tensor | None, drop: float,
                 attn_drop: float, ff_ratio: float):
        super().__init__()
        self.window_size = window_size
        self.temporal_patch_size = temporal_patch_size
        self.temporal_dim = temporal_dim
        self.num_kps = num_kps
        self.shift_size = shift_size
        self.norm1 = nn.LayerNorm(dim)
        self.attn = MSA(dim, num_heads=num_heads, adj_mat=adj_mat, attn_drop=attn_drop, proj_drop=drop)
        self.norm2 = nn.LayerNorm(dim)
        self.ff = FeedForward(dim, int(dim * ff_ratio), drop=drop)
        if self.shift_size > 0:
            F, K = temporal_dim, num_kps
            frame_mask = torch.zeros((1, F, K, 1))
            t_slices = (slice(0, -temporal_patch_size), slice(-temporal_patch_size, -shift_size),
                        slice(-shift_size, None))
            cnt = 0
            for t in t_slices:
                frame_mask[:, t, :] = cnt
                cnt += 1
            mask_windows = window_partition(frame_mask, window_size, temporal_patch_size).squeeze(2)
            attn_mask = mask_windows.unsqueeze(1) - mask_windows.unsqueeze(2)
            attn_mask = attn_mask.masked_fill(attn_mask != 0, float(0.0)).masked_fill(attn_mask == 0, float(1))
        else:
            attn_mask = None
        self.register_buffer("attn_mask", attn_mask)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        W, TP = self.window_size, self.temporal_patch_size
        B, F, K, ED = x.shape
        f, nW = F // TP, K // W
        shortcut = x
        shifted = torch.roll(x, shifts=-self.shift_size, dims=1) if self.shift_size > 0 else x
        x = window_partition(shifted, W, TP)
        x = self.norm1(x)
        x = self.attn(x, B, f, nW, mask=self.attn_mask)
        x = window_reverse(x, W, TP, F, K)
        shifted = torch.roll(x, shifts=self.shift_size, dims=1) if self.shift_size > 0 else x
        x = shortcut + shifted
        return x + self.ff(self.norm2(x))


class PartAttentionLayer(nn.Module):
    def __init__(self, dim: int, temporal_patch_size: int, temporal_dim: int, num_kps: int, depth: int,
                 num_heads: int, window_size: int, adj_mat: torch.Tensor | None, drop: float, attn_drop: float,
                 ff_ratio: float, downsample: bool):
        super().__init__()
        self.blocks = nn.ModuleList([
            PartAttentionBlock(dim=dim, num_kps=num_kps, num_heads=num_heads, window_size=window_size,
                               temporal_patch_size=temporal_patch_size, temporal_dim=temporal_dim,
                               shift_size=0 if (i % 2 == 0) else temporal_patch_size // 2,
                               adj_mat=adj_mat, drop=drop, attn_drop=attn_drop, ff_ratio=ff_ratio)
            for i in range(depth)])
        self.downsample = TemporalMerging(dim, temporal_patch_size) if downsample else None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for blk in self.blocks:
            x = blk(x)
        if self.downsample is not None:
            x = self.downsample(x)
        return x


# Skeleton edges inside each 16-keypoint window (identical for the 4 windows upstream)
_WINDOW_EDGES = [[0, 1], [0, 2], [0, 3], [3, 4], [4, 5], [5, 6], [6, 7], [6, 8], [8, 9], [8, 10], [6, 10],
                 [10, 11], [10, 12], [6, 12], [12, 13], [12, 14], [14, 15], [6, 14], [7, 9], [9, 11],
                 [11, 13], [13, 15], [7, 15], [7, 11], [7, 13]]


def build_adj_mat(window_size: int = 16, temporal_patch_size: int = 2, num_kps: int = 64) -> torch.Tensor:
    def adj_one() -> np.ndarray:
        a = np.eye(window_size)
        for i, j in _WINDOW_EDGES:
            a[i, j] = 1
            a[j, i] = 1
        return a
    TP, W, K = temporal_patch_size, window_size, num_kps
    out = []
    for _ in range(K // W):
        rows = []
        for i in range(TP):
            row = []
            for j in range(TP):
                if i == j:
                    row.append(adj_one())
                elif abs(i - j) == 1:
                    row.append(np.eye(W))
                else:
                    row.append(np.zeros((W, W)))
            rows.append(np.concatenate(row, axis=1))
        out.append(np.concatenate(rows))
    return torch.tensor(np.array(out), dtype=torch.float32)


class HWGATModel(nn.Module):
    """Configuration fixed to the released FDMSE checkpoint (embed 128, depths [4,4,8], heads [2,4,8])."""

    def __init__(self, num_classes: int = NUM_CLASSES, kp_dim: int = 2, num_kps: int = 64,
                 temporal_dim: int = SRC_LEN, embed_dim: int = 128, temporal_patch_size: int = 2,
                 depths: Sequence[int] = (4, 4, 8), num_heads: Sequence[int] = (2, 4, 8),
                 window_size: int = 16, drop_rate: float = 0.1, attn_drop_rate: float = 0.0,
                 ff_ratio: float = 2.0):
        super().__init__()
        self.num_layers = len(depths)
        self.num_kps = num_kps
        self.num_features = int(embed_dim * 2 ** (self.num_layers - 1))
        self.temporal_out_dim = temporal_dim // temporal_patch_size ** (self.num_layers - 1)
        adj_mat = build_adj_mat(window_size, temporal_patch_size, num_kps)
        self.B = nn.Parameter(torch.zeros(embed_dim // 2, kp_dim), requires_grad=False)  # loaded from ckpt
        self.pos_encoder = PositionalEncoding(embed_dim, drop_rate, temporal_dim)
        self.layers = nn.ModuleList()
        for i_layer in range(self.num_layers):
            adj_t = torch.cat([adj_mat for _ in range(temporal_dim // temporal_patch_size ** (i_layer + 1))])
            self.layers.append(PartAttentionLayer(
                dim=int(embed_dim * 2 ** i_layer), temporal_patch_size=temporal_patch_size,
                temporal_dim=temporal_dim // (temporal_patch_size ** i_layer), num_kps=num_kps,
                depth=depths[i_layer], num_heads=num_heads[i_layer], window_size=window_size,
                adj_mat=adj_t, drop=drop_rate, attn_drop=attn_drop_rate, ff_ratio=ff_ratio,
                downsample=i_layer < self.num_layers - 1))
        self.norm = nn.LayerNorm(self.num_features)
        self.avgpool = nn.AvgPool1d(self.temporal_out_dim * self.num_kps)
        self.head = nn.Linear(self.num_features, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # x: (B, 192, 64, 2)
        x_proj = (2.0 * torch.pi * x) @ self.B.transpose(1, 0)
        x = torch.cat([torch.sin(x_proj), torch.cos(x_proj)], dim=-1)
        x = self.pos_encoder(x)
        for layer in self.layers:
            x = layer(x)
        B, f, K, d = x.shape
        x = self.norm(x)
        x = self.avgpool(x.transpose(1, 3).reshape(B, d, -1)).squeeze(-1)
        return self.head(x)

    @classmethod
    def from_checkpoint(cls, path: str, device: str | torch.device = "cpu") -> "HWGATModel":
        ckpt = torch.load(path, map_location="cpu", weights_only=False)
        state = ckpt["model_state_dict"] if "model_state_dict" in ckpt else ckpt
        model = cls()
        model.load_state_dict(state, strict=True)
        return model.to(device).eval()


# ---------------------------------------------------------------------------
# Preprocessing (reproduces sl-hwgat-demo test_transform)
# ---------------------------------------------------------------------------

_POSE_SEL = [NOSE, L_EYE, R_EYE, L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW, L_WRIST, R_WRIST]
_HAND_SEL = [0, 4, 5, 8, 9, 12, 13, 16, 17, 20]
LEFT_SLICE = (9, 19, 7)    # kp indices of the left hand and the left-wrist fallback
RIGHT_SLICE = (19, 29, 8)
_PARTS = {"head": [0, 1, 2], "l_arm": [3, 5, 7], "l_hand": list(range(9, 19)),
          "r_arm": [4, 6, 8], "r_hand": list(range(19, 29))}
_WINDOWS = [_PARTS["head"] + _PARTS["l_arm"] + _PARTS["l_hand"],
            _PARTS["head"] + _PARTS["r_arm"] + _PARTS["r_hand"],
            _PARTS["head"] + _PARTS["l_arm"] + _PARTS["r_hand"],
            _PARTS["head"] + _PARTS["r_arm"] + _PARTS["l_hand"]]


def frames_to_kp29(frames: Sequence[LandmarkFrame]) -> np.ndarray:
    """(T, 29, 2) pixel coordinates; missing parts are zeros (upstream convention)."""
    out = np.zeros((len(frames), 29, 2), dtype=np.float64)
    for t, f in enumerate(frames):
        scale = np.array([f.width, f.height], dtype=np.float64)
        if f.pose is not None:
            out[t, 0:9] = f.pose[_POSE_SEL, :2] * scale
        if f.left_hand is not None:
            out[t, 9:19] = f.left_hand[_HAND_SEL, :2] * scale
        if f.right_hand is not None:
            out[t, 19:29] = f.right_hand[_HAND_SEL, :2] * scale
    return out


def hand_correction(v: np.ndarray, slices: tuple[int, int, int], k_spline: int = 2) -> np.ndarray:
    """Fill missing hand frames: wrist position at the edges, quadratic spline inside."""
    s0, s1, wrist = slices
    if np.sum(v[:, s0:s1]) == 0:
        v[:, s0:s1, :] = np.expand_dims(v[:, wrist, :], axis=1)
        return v
    start = end = 0
    for i in range(len(v)):
        if not v[i, s0:s1].any():
            v[i, s0:s1, :] = np.expand_dims(v[i, wrist, :], axis=0)
        else:
            start = i
            break
    for i in reversed(range(len(v))):
        if not v[i, s0:s1].any():
            v[i, s0:s1, :] = np.expand_dims(v[i, wrist, :], axis=0)
        else:
            end = i
            break
    present = [i for i in range(start, end + 1) if v[i, s0:s1].any()]
    missing = [i for i in range(start, end + 1) if not v[i, s0:s1].any()]
    if missing and len(present) > k_spline:
        try:
            for kp in range(s0, s1):
                xs = v[present, kp, 0]
                ys = v[present, kp, 1]
                tx = interpolate.splrep(present, xs, k=k_spline)
                ty = interpolate.splrep(present, ys, k=k_spline)
                for m in missing:
                    v[m, kp, 0] = interpolate.splev(m, tx)
                    v[m, kp, 1] = interpolate.splev(m, ty)
        except Exception:  # upstream swallows spline failures too
            pass
    return v


def normalize_keypoints(v: np.ndarray, origin_idx: int = 0, anchors: tuple[int, int] = (3, 4)) -> np.ndarray | None:
    """Nose-origin, shoulder-width scaled box (upstream NormalizeKeypoints)."""
    for kp in v:
        if kp[origin_idx].all() != 0 and kp[anchors[0]].all() != 0 and kp[anchors[1]].all() != 0:
            root = kp[origin_idx]
            unit = np.linalg.norm(kp[anchors[0]] - kp[anchors[1]])
            if unit < 1e-6:
                continue
            left_top = root - 3 * unit
            left_top[1] = root[1] - 2 * unit
            return (v - left_top) / (6 * unit)
    return None


def temporal_sample(x: np.ndarray, max_len: int = SRC_LEN) -> np.ndarray:
    if x.shape[0] <= max_len:
        index = int((max_len - x.shape[0]) * 0.5)
        front = np.full((max_len // 2, x.shape[1], x.shape[2]), x[0], dtype=np.float32)
        back = np.full((max_len - max_len // 2, x.shape[1], x.shape[2]), x[-1], dtype=np.float32)
        out = np.concatenate([front, back], axis=0)
        out[index:index + x.shape[0]] = x
        return out
    idx = np.linspace(0, x.shape[0] - 1, num=max_len).astype(int)
    return x[idx].astype(np.float32)


def window_create(v: np.ndarray) -> np.ndarray:
    out = np.zeros((v.shape[0], 64, v.shape[-1]), dtype=np.float32)
    for w, idx in enumerate(_WINDOWS):
        out[:, w * 16:(w + 1) * 16] = v.take(idx, 1)
    return out


def preprocess(frames: Sequence[LandmarkFrame]) -> np.ndarray | None:
    """LandmarkFrames -> (192, 64, 2) float32 model input, or None if no usable pose."""
    if len(frames) == 0:
        return None
    v = frames_to_kp29(frames)
    v = hand_correction(v, LEFT_SLICE)
    v = hand_correction(v, RIGHT_SLICE)
    v = normalize_keypoints(v)
    if v is None:
        return None
    v = temporal_sample(v.astype(np.float32))
    return window_create(v)
