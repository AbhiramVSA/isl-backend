"""Model-level tests; skipped when checkpoints are not downloaded."""
from pathlib import Path

import numpy as np
import pytest
import torch

from app.config import settings
from app.models import hwgat, include_features, stgcnpp
from app.models.include_transformer import IncludeTransformer

M = settings.models_dir


def test_hwgat_preprocess_shapes(frame_factory):
    frames = [frame_factory(i * 40.0) for i in range(30)]
    x = hwgat.preprocess(frames)
    assert x.shape == (192, 64, 2)
    assert np.isfinite(x).all()
    # no pose at all -> None (never fabricate an input)
    for f in frames:
        f.pose = None
    assert hwgat.preprocess(frames) is None


def test_include_preprocess_shapes(frame_factory):
    frames = [frame_factory(i * 40.0) for i in range(30)]
    frames[5].left_hand = None            # missing hand is interpolated, not zeroed
    x = include_features.preprocess(frames)
    assert x.shape == (169, 134)
    assert np.isfinite(x).all()
    assert x[5, 50:92].any()


def test_stgcn_preprocess_shape():
    kp = np.random.rand(40, 17, 2).astype(np.float32) * 400
    sc = np.random.rand(40, 17).astype(np.float32)
    x = stgcnpp.preprocess(kp, sc, 640, 480)
    assert x.shape == (1, 2, 100, 17, 3)
    assert x[0, 1].sum() == 0          # second person zero-padded
    assert np.abs(x[0, 0, :, :, :2]).max() <= 1.0 + 1e-5


@pytest.mark.skipif(not (M / "hwgat" / "model_best_loss.pt").exists(), reason="HWGAT weights not downloaded")
def test_hwgat_loads_strict_and_runs():
    m = hwgat.HWGATModel.from_checkpoint(str(M / "hwgat" / "model_best_loss.pt"))
    y = m(torch.zeros(1, 192, 64, 2))
    assert y.shape == (1, 2002)


@pytest.mark.skipif(not (M / "include" / "include_no_cnn_transformer_large.pth").exists(), reason="INCLUDE weights not downloaded")
def test_include_loads_strict_and_runs():
    m = IncludeTransformer.from_checkpoint(str(M / "include" / "include_no_cnn_transformer_large.pth"), "large", 263)
    y = m(torch.zeros(1, 169, 134))
    assert y.shape == (1, 263)
    # deterministic (upstream evaluate.py applied dropout at inference; we do not)
    assert torch.equal(m(torch.ones(1, 169, 134)), m(torch.ones(1, 169, 134)))


@pytest.mark.skipif(not (M / "stgcnpp" / "stgcnpp_ntu60_xsub_hrnet_j.pth").exists(), reason="ST-GCN++ weights not downloaded")
def test_stgcn_loads_strict_and_runs():
    m = stgcnpp.STGCNpp.from_checkpoint(str(M / "stgcnpp" / "stgcnpp_ntu60_xsub_hrnet_j.pth"))
    y = m(torch.zeros(1, 2, 100, 17, 3))
    assert y.shape == (1, 60)
    assert stgcnpp.NTU60_LABELS[stgcnpp.IDX_FALLING] == "falling"
