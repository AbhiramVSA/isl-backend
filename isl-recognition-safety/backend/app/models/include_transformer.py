"""Standalone PyTorch reimplementation of the AI4Bharat INCLUDE keypoint Transformer.

The original (https://github.com/AI4Bharat/INCLUDE, MIT) wraps
``transformers.BertLayer``; this file reimplements the post-LayerNorm BERT
encoder layer in plain PyTorch so the published checkpoints load with
``strict=True`` without depending on a specific ``transformers`` release.

Input: (batch, frames, 134) float tensor of raw keypoints in 1920x1080 pixel
space, laid out as [pose(25 x,y) | hand1(21 x,y) | hand2(21 x,y)], zero-padded
to a fixed frame length (169 in the upstream evaluate.py).
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F

INPUT_SIZE = 134
MAX_POSITIONS = 256


class _SelfAttention(nn.Module):
    def __init__(self, hidden: int, heads: int):
        super().__init__()
        self.query = nn.Linear(hidden, hidden)
        self.key = nn.Linear(hidden, hidden)
        self.value = nn.Linear(hidden, hidden)
        self.heads = heads
        self.head_dim = hidden // heads

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, t, h = x.shape
        q = self.query(x).view(b, t, self.heads, self.head_dim).transpose(1, 2)
        k = self.key(x).view(b, t, self.heads, self.head_dim).transpose(1, 2)
        v = self.value(x).view(b, t, self.heads, self.head_dim).transpose(1, 2)
        scores = q @ k.transpose(-1, -2) / math.sqrt(self.head_dim)
        probs = scores.softmax(dim=-1)
        ctx = (probs @ v).transpose(1, 2).reshape(b, t, h)
        return ctx


class _AttentionOutput(nn.Module):
    def __init__(self, hidden: int, eps: float):
        super().__init__()
        self.dense = nn.Linear(hidden, hidden)
        self.LayerNorm = nn.LayerNorm(hidden, eps=eps)

    def forward(self, x: torch.Tensor, residual: torch.Tensor) -> torch.Tensor:
        return self.LayerNorm(self.dense(x) + residual)


class _Attention(nn.Module):
    def __init__(self, hidden: int, heads: int, eps: float):
        super().__init__()
        self.self = _SelfAttention(hidden, heads)
        self.output = _AttentionOutput(hidden, eps)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.output(self.self(x), x)


class _Intermediate(nn.Module):
    def __init__(self, hidden: int, inter: int):
        super().__init__()
        self.dense = nn.Linear(hidden, inter)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.gelu(self.dense(x))


class _Output(nn.Module):
    def __init__(self, hidden: int, inter: int, eps: float):
        super().__init__()
        self.dense = nn.Linear(inter, hidden)
        self.LayerNorm = nn.LayerNorm(hidden, eps=eps)

    def forward(self, x: torch.Tensor, residual: torch.Tensor) -> torch.Tensor:
        return self.LayerNorm(self.dense(x) + residual)


class BertLayer(nn.Module):
    """Post-LN BERT encoder layer; parameter names match HF ``BertLayer``."""

    def __init__(self, hidden: int, heads: int, inter: int = 3072, eps: float = 1e-12):
        super().__init__()
        self.attention = _Attention(hidden, heads, eps)
        self.intermediate = _Intermediate(hidden, inter)
        self.output = _Output(hidden, inter, eps)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        a = self.attention(x)
        return self.output(self.intermediate(a), a)


class PositionEmbedding(nn.Module):
    def __init__(self, hidden: int, max_positions: int = MAX_POSITIONS, eps: float = 1e-12):
        super().__init__()
        self.position_embeddings = nn.Embedding(max_positions, hidden)
        self.LayerNorm = nn.LayerNorm(hidden, eps=eps)
        self.register_buffer("position_ids", torch.arange(max_positions).expand((1, -1)))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        t = x.size(1)
        return self.LayerNorm(x + self.position_embeddings(self.position_ids[:, :t]))


class IncludeTransformer(nn.Module):
    """INCLUDE keypoint transformer. ``size`` is "large" (512d, 8 heads, 4 layers)
    or "small" (256d, 4 heads, 2 layers)."""

    def __init__(self, size: str = "large", n_classes: int = 263):
        super().__init__()
        if size == "large":
            hidden, heads, layers = 512, 8, 4
        elif size == "small":
            hidden, heads, layers = 256, 4, 2
        else:
            raise ValueError(f"unknown size {size!r}")
        self.l1 = nn.Linear(INPUT_SIZE, hidden)
        self.embedding = PositionEmbedding(hidden)
        self.layers = nn.ModuleList([BertLayer(hidden, heads) for _ in range(layers)])
        self.l2 = nn.Linear(hidden, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.embedding(self.l1(x))
        for layer in self.layers:
            x = layer(x)
        x = torch.max(x, dim=1).values  # temporal max-pool (dropout is identity in eval)
        return self.l2(x)

    @classmethod
    def from_checkpoint(cls, path: str, size: str = "large", n_classes: int = 263,
                        device: str | torch.device = "cpu") -> "IncludeTransformer":
        ckpt = torch.load(path, map_location="cpu", weights_only=False)
        state = ckpt["model"] if isinstance(ckpt, dict) and "model" in ckpt else ckpt
        model = cls(size=size, n_classes=n_classes)
        model.load_state_dict(state, strict=True)
        return model.to(device).eval()
