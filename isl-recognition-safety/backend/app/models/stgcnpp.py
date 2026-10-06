"""Torch-only ST-GCN++ (pyskl layout) for NTU RGB+D 60 skeleton action recognition.

Loads pyskl checkpoints (Apache-2.0, https://github.com/kennymckormick/pyskl) without mmcv:
``stgcnpp_ntu60_xsub_hrnet/j.pth`` (joint modality, COCO-17 2D keypoints from HRNet,
89.3% top-1 cross-subject). Preprocessing reproduces pyskl's test pipeline:
PreNormalize2D(mode='fix') -> UniformSampleFrames(100, test) -> FormatGCNInput(num_person=2).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import torch
import torch.nn as nn

CLIP_LEN = 100

NTU60_LABELS = [
    "drink water", "eat meal/snack", "brushing teeth", "brushing hair", "drop", "pickup", "throw",
    "sitting down", "standing up (from sitting position)", "clapping", "reading", "writing",
    "tear up paper", "wear jacket", "take off jacket", "wear a shoe", "take off a shoe",
    "wear on glasses", "take off glasses", "put on a hat/cap", "take off a hat/cap", "cheer up",
    "hand waving", "kicking something", "reach into pocket", "hopping (one foot jumping)", "jump up",
    "make a phone call/answer phone", "playing with phone/tablet", "typing on a keyboard",
    "pointing to something with finger", "taking a selfie", "check time (from watch)",
    "rub two hands together", "nod head/bow", "shake head", "wipe face", "salute",
    "put the palms together", "cross hands in front (say stop)", "sneeze/cough", "staggering",
    "falling", "touch head (headache)", "touch chest (stomachache/heart pain)", "touch back (backache)",
    "touch neck (neckache)", "nausea or vomiting condition", "use a fan (with hand or paper)/feeling warm",
    "punching/slapping other person", "kicking other person", "pushing other person",
    "pat on back of other person", "point finger at the other person", "hugging other person",
    "giving something to other person", "touch other person's pocket", "handshaking",
    "walking towards each other", "walking apart from each other",
]
assert len(NTU60_LABELS) == 60

# 0-based indices of safety-relevant classes
IDX_FALLING = 42
IDX_STAGGERING = 41
IDX_MEDICAL = [40, 43, 44, 45, 46, 47]      # sneeze/cough, headache, chest, back, neck, nausea
IDX_WAVE = [21, 22]                           # cheer up, hand waving
IDX_SIT_STAND = [7, 8]
IDX_STOP = 39

COCO_INWARD = [(15, 13), (13, 11), (16, 14), (14, 12), (11, 5), (12, 6), (9, 7), (7, 5), (10, 8), (8, 6),
               (5, 0), (6, 0), (1, 0), (3, 1), (2, 0), (4, 2)]


def _edge2mat(link, n):
    A = np.zeros((n, n))
    for i, j in link:
        A[j, i] = 1
    return A


def _normalize_digraph(A):
    Dl = np.sum(A, 0)
    w = A.shape[1]
    Dn = np.zeros((w, w))
    for i in range(w):
        if Dl[i] > 0:
            Dn[i, i] = Dl[i] ** (-1)
    return np.dot(A, Dn)


def coco_spatial_A() -> np.ndarray:
    n = 17
    inward = COCO_INWARD
    outward = [(j, i) for i, j in inward]
    I = _edge2mat([(i, i) for i in range(n)], n)
    In = _normalize_digraph(_edge2mat(inward, n))
    Out = _normalize_digraph(_edge2mat(outward, n))
    return np.stack((I, In, Out))


class unit_tcn(nn.Module):
    def __init__(self, cin, cout, kernel_size=9, stride=1, dilation=1, norm="BN", dropout=0.0):
        super().__init__()
        pad = (kernel_size + (kernel_size - 1) * (dilation - 1) - 1) // 2
        self.conv = nn.Conv2d(cin, cout, (kernel_size, 1), padding=(pad, 0), stride=(stride, 1),
                              dilation=(dilation, 1))
        self.bn = nn.BatchNorm2d(cout) if norm is not None else nn.Identity()
        self.drop = nn.Dropout(dropout, inplace=True)

    def forward(self, x):
        return self.drop(self.bn(self.conv(x)))


class mstcn(nn.Module):
    def __init__(self, cin, cout, dropout=0.0, ms_cfg=((3, 1), (3, 2), (3, 3), (3, 4), ("max", 3), "1x1"),
                 stride=1):
        super().__init__()
        nb = len(ms_cfg)
        self.act = nn.ReLU()
        mid = cout // nb
        rem = cout - mid * (nb - 1)
        branches = []
        for i, cfg in enumerate(ms_cfg):
            bc = rem if i == 0 else mid
            if cfg == "1x1":
                branches.append(nn.Conv2d(cin, bc, 1, stride=(stride, 1)))
                continue
            if cfg[0] == "max":
                branches.append(nn.Sequential(nn.Conv2d(cin, bc, 1), nn.BatchNorm2d(bc), self.act,
                                              nn.MaxPool2d((cfg[1], 1), stride=(stride, 1), padding=(1, 0))))
                continue
            branches.append(nn.Sequential(nn.Conv2d(cin, bc, 1), nn.BatchNorm2d(bc), self.act,
                                          unit_tcn(bc, bc, kernel_size=cfg[0], stride=stride, dilation=cfg[1],
                                                   norm=None)))
        self.branches = nn.ModuleList(branches)
        tin = mid * (nb - 1) + rem
        self.transform = nn.Sequential(nn.BatchNorm2d(tin), self.act, nn.Conv2d(tin, cout, 1))
        self.bn = nn.BatchNorm2d(cout)
        self.drop = nn.Dropout(dropout, inplace=True)

    def forward(self, x):
        feat = self.transform(torch.cat([b(x) for b in self.branches], 1))
        return self.drop(self.bn(feat))


class unit_gcn(nn.Module):
    def __init__(self, cin, cout, A, with_res=True):
        super().__init__()
        self.num_subsets = A.size(0)
        self.with_res = with_res
        self.bn = nn.BatchNorm2d(cout)
        self.act = nn.ReLU()
        self.A = nn.Parameter(A.clone())  # adaptive='init'
        self.conv = nn.Conv2d(cin, cout * A.size(0), 1)
        if with_res:
            self.down = (nn.Sequential(nn.Conv2d(cin, cout, 1), nn.BatchNorm2d(cout)) if cin != cout
                         else nn.Identity())

    def forward(self, x):
        n, c, t, v = x.shape
        res = self.down(x) if self.with_res else 0
        x = self.conv(x).view(n, self.num_subsets, -1, t, v)
        x = torch.einsum("nkctv,kvw->nctw", x, self.A).contiguous()
        return self.act(self.bn(x) + res)


class STGCNBlock(nn.Module):
    def __init__(self, cin, cout, A, stride=1, residual=True):
        super().__init__()
        self.gcn = unit_gcn(cin, cout, A)
        self.tcn = mstcn(cout, cout, stride=stride)
        self.relu = nn.ReLU()
        if not residual:
            self.residual = None
        elif cin == cout and stride == 1:
            self.residual = nn.Identity()
        else:
            self.residual = unit_tcn(cin, cout, kernel_size=1, stride=stride)

    def forward(self, x):
        res = 0 if self.residual is None else self.residual(x)
        return self.relu(self.tcn(self.gcn(x)) + res)


class STGCNpp(nn.Module):
    def __init__(self, num_classes=60, in_channels=3, base=64, num_stages=10, inflate=(5, 8), down=(5, 8),
                 ch_ratio=2):
        super().__init__()
        A = torch.tensor(coco_spatial_A(), dtype=torch.float32)
        V = A.size(1)
        self.data_bn = nn.BatchNorm1d(in_channels * V)
        mods = [STGCNBlock(in_channels, base, A.clone(), 1, residual=False)]
        inflate_times = 0
        for i in range(2, num_stages + 1):
            stride = 1 + (i in down)
            cin = base
            if i in inflate:
                inflate_times += 1
            cout = int(64 * ch_ratio ** inflate_times + 1e-6)
            base = cout
            mods.append(STGCNBlock(cin, cout, A.clone(), stride))
        self.gcn = nn.ModuleList(mods)
        self.fc_cls = nn.Linear(base, num_classes)
        self.pool = nn.AdaptiveAvgPool2d(1)

    def forward(self, x):  # (N, M, T, V, C)
        N, M, T, V, C = x.shape
        x = x.permute(0, 1, 3, 4, 2).contiguous()
        x = self.data_bn(x.view(N * M, V * C, T))
        x = x.view(N, M, V, C, T).permute(0, 1, 3, 4, 2).contiguous().view(N * M, C, T, V)
        for blk in self.gcn:
            x = blk(x)
        x = self.pool(x).view(N, M, -1).mean(1)
        return self.fc_cls(x)

    @classmethod
    def from_checkpoint(cls, path: str, device: str | torch.device = "cpu") -> "STGCNpp":
        sd = torch.load(path, map_location="cpu", weights_only=False)
        if "state_dict" in sd:
            sd = sd["state_dict"]
        new = {}
        for k, v in sd.items():
            if k.startswith("backbone."):
                k = k[len("backbone."):]
            elif k.startswith("cls_head."):
                k = k[len("cls_head."):]
            new[k] = v
        model = cls()
        model.load_state_dict(new, strict=True)
        return model.to(device).eval()


# ---------------------------------------------------------------------------
# Preprocessing: pyskl test pipeline
# ---------------------------------------------------------------------------

def preprocess(kpts: np.ndarray, scores: np.ndarray, width: int, height: int, threshold: float = 0.01,
               clip_len: int = CLIP_LEN) -> np.ndarray:
    """kpts (T, 17, 2) pixels, scores (T, 17) -> (1, 2, clip_len, 17, 3) float32 (person 2 zero-padded)."""
    T = kpts.shape[0]
    kp = kpts.astype(np.float32).copy()
    sc = scores.astype(np.float32).copy()
    kp[..., 0] = (kp[..., 0] - width / 2) / (width / 2)
    kp[..., 1] = (kp[..., 1] - height / 2) / (height / 2)
    low = sc <= threshold
    kp[low] = 0
    sc[low] = 0
    if T >= clip_len:  # uniform sample: middle of each equal segment
        seg = T / clip_len
        idx = (np.arange(clip_len) * seg + seg / 2).astype(int)
        idx = np.clip(idx, 0, T - 1)
    else:              # loop
        idx = np.arange(clip_len) % T
    kp, sc = kp[idx], sc[idx]
    feat = np.concatenate([kp, sc[..., None]], axis=-1)  # (clip_len, 17, 3)
    out = np.zeros((1, 2, clip_len, 17, 3), dtype=np.float32)
    out[0, 0] = feat
    return out
