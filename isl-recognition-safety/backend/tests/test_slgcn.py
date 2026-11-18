"""SL-GCN (OpenHands INCLUDE) tests; the weight-dependent ones skip when the state dict is absent."""
import numpy as np
import pytest
import torch

from app.models import slgcn


def test_graph_and_presets():
    A = slgcn.spatial_graph()
    assert A.shape == (3, 27, 27)
    assert np.allclose(A[0], np.eye(27))
    # inward/outward blocks are column-normalised (each node's incoming weights sum to 1 or 0)
    for k in (1, 2):
        col = A[k].sum(0)
        assert np.all((np.isclose(col, 1) | np.isclose(col, 0)))
    assert len(slgcn.POSE_INDEXES_27) == 27
    assert slgcn.POSE_INDEXES_27[3:5] == [11, 12]        # reference points 3,4 are the shoulders
    assert slgcn.POSE_INDEXES_27[7] == 33 and slgcn.POSE_INDEXES_27[17] == 54   # wrists head each hand block


def test_preprocess_shape_and_normalisation(frame_factory):
    frames = [frame_factory(i * 40.0) for i in range(30)]
    frames[5].left_hand = None                          # missing hand -> zeros, like generate_pose.py
    x = slgcn.preprocess(frames)
    assert x.shape == (2, 30, 27)
    assert x.dtype == np.float32 and np.isfinite(x).all()
    # clip-level CenterAndScaleNormalize: mean shoulder midpoint at origin, mean shoulder distance 1
    mid = (x[:, :, 3] + x[:, :, 4]) / 2
    assert np.allclose(mid.mean(1), 0, atol=1e-5)
    dist = np.sqrt(((x[:, :, 3] - x[:, :, 4]) ** 2).sum(0))
    assert np.isclose(dist.mean(), 1.0, atol=1e-5)
    # the zeroed hand maps to (-center) * scale, not to 0
    assert not np.allclose(x[:, 5, 7:17], 0)
    # frames without pose are skipped; none at all -> None
    frames[0].pose = None
    assert slgcn.preprocess(frames).shape == (2, 29, 27)
    for f in frames:
        f.pose = None
    assert slgcn.preprocess(frames) is None
    assert slgcn.preprocess([]) is None


def test_preprocess_emulate_aspect(frame_factory):
    frames = [frame_factory(i * 40.0, width=640, height=480) for i in range(10)]
    a = slgcn.preprocess(frames)
    b = slgcn.preprocess(frames, emulate_aspect=4 / 3)  # same aspect as the source -> no change
    assert np.allclose(a, b, atol=1e-6)
    c = slgcn.preprocess(frames, emulate_aspect=16 / 9)
    assert c.shape == a.shape and not np.allclose(a, c)


def test_display_labels():
    assert slgcn.display_label("1.Dog") == "Dog"
    assert slgcn.display_label("Ex.Monsoon") == "Monsoon"
    assert slgcn.display_label("Second(Number)") == "Second (number)"
    assert slgcn.display_label("55.Thankyou") == "Thank you"
    assert slgcn.display_label("11.rich") == "Rich"


@pytest.mark.skipif(not slgcn.DEFAULT_CLASSES.exists(), reason="INCLUDE class list not present")
def test_labels_file():
    labels, display = slgcn.load_labels()
    assert len(labels) == len(display) == 263
    assert labels == sorted(labels)                      # OpenHands sorted(set(df["Word"])) order
    assert labels[0] == "1.Dog" and display[0] == "Dog"
    assert slgcn.LABELS == labels and slgcn.DISPLAY_LABELS == display


def test_untrained_forward_shapes():
    m = slgcn.SLGCN(num_classes=263).eval()
    for T in (1, 5, 40):
        y = m(torch.zeros(1, 2, T, 27))
        assert y.shape == (1, 263)


@pytest.mark.skipif(not slgcn.DEFAULT_STATE_DICT.exists(), reason="SL-GCN weights not present")
def test_slgcn_loads_strict_and_runs(frame_factory):
    m = slgcn.SLGCN.from_state_dict(slgcn.DEFAULT_STATE_DICT)
    assert not m.training
    x = slgcn.preprocess([frame_factory(i * 40.0) for i in range(30)])
    y = m(torch.from_numpy(x)[None])
    assert y.shape == (1, 263) and torch.isfinite(y).all()
    assert torch.equal(m(torch.ones(1, 2, 20, 27)), m(torch.ones(1, 2, 20, 27)))   # deterministic
