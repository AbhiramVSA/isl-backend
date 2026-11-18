"""Recognizer/fusion tests with fake heads (no checkpoints needed)."""
import numpy as np

from app.models.registry import TopK
from app.recognition.recognizer import SignRecognizer


class FakeHead:
    def __init__(self, labels, dist):
        self.labels = labels
        self.dist = dist  # dict label -> p

    def predict(self, frames):
        probs = np.zeros(len(self.labels), np.float32)
        for k, v in self.dist.items():
            probs[self.labels.index(k)] = v
        idx = np.argsort(-probs)[:5]
        return TopK(top=[{"label": self.labels[i], "index": int(i), "p": float(probs[i])} for i in idx],
                    latency_ms=1.0, probs=probs)


class FakeRegistry:
    class device:
        type = "cpu"

    def __init__(self, hwgat=None, include=None, slgcn=None):
        self.hwgat, self.include, self.slgcn, self.action = hwgat, include, slgcn, None


HW = ["Water", "Laptop", "Help [VEB]", "Television/T.V.", "Good Evening", "Thank You"]
INC = ["water", "laptop", "television", "goodevening", "thankyou", "hello"]


def _rec(hw_dist, inc_dist=None):
    reg = FakeRegistry(FakeHead(HW, hw_dist), FakeHead(INC, inc_dist) if inc_dist is not None else None)
    return SignRecognizer(reg, {"HELP": {"Help [VEB]"}})


def test_alias_mapping_and_agreement():
    rec = _rec({"Television/T.V.": 0.6, "Water": 0.2}, {"television": 0.7, "water": 0.1})
    fused = rec._fuse(rec._run_heads([]))
    assert fused["label"] == "Television/T.V." and fused["agreement"] is True
    assert fused["p"] > 0.6


def test_disagreement_lowers_confidence():
    rec = _rec({"Water": 0.9}, {"laptop": 0.9})
    fused = rec._fuse(rec._run_heads([]))
    assert fused["p"] < 0.8 and fused["agreement"] is False   # 0.9 alone would have been confident


def test_unsure_primary_defers_to_secondary():
    rec = _rec({"Water": 0.05, "Laptop": 0.04}, {"goodevening": 0.5})
    fused = rec._fuse(rec._run_heads([]))
    assert fused["label"] == "Good Evening"
    assert 0.3 < fused["p"] < 0.55


def test_three_heads_two_agree_beat_one():
    reg = FakeRegistry(FakeHead(HW, {"Water": 0.5, "Laptop": 0.3}), FakeHead(INC, {"laptop": 0.9}),
                       FakeHead(["Water", "Laptop", "Dog"], {"Laptop": 0.95}))
    rec = SignRecognizer(reg, {})
    fused = rec._fuse(rec._run_heads([]))
    assert fused["label"] == "Laptop" and fused["agreement"] is True
    assert set(fused["weights"]) == {"hwgat", "include", "slgcn"}


def test_broken_head_does_not_stop_others():
    class Broken:
        labels = ["x"]

        def predict(self, frames):
            raise RuntimeError("boom")
    reg = FakeRegistry(FakeHead(HW, {"Water": 0.9}), Broken())
    rec = SignRecognizer(reg, {})
    heads = rec._run_heads([])
    assert set(heads) == {"hwgat"}


def test_emits_unknown_when_nothing_confident(frame_factory):
    rec = _rec({"Water": 0.1, "Laptop": 0.08}, {"hello": 0.1})
    t = 0.0
    for i in range(60):
        rec.process(frame_factory(t, hand_offset=(0.05 * np.sin(i), 0.05 * np.cos(i)))); t += 33
    for i in range(40):
        rec.process(frame_factory(t)); t += 33
    assert len(rec.glosses) == 1 and rec.glosses[0].status == "unknown" and rec.glosses[0].label == "UNKNOWN"


def test_emits_confident_gloss_with_safety_lexicon(frame_factory):
    rec = _rec({"Help [VEB]": 0.85, "Water": 0.05}, {"hello": 0.2})
    t = 0.0
    for i in range(60):
        rec.process(frame_factory(t, hand_offset=(0.05 * np.sin(i), 0.05 * np.cos(i)))); t += 33
    for i in range(40):
        rec.process(frame_factory(t)); t += 33
    assert len(rec.glosses) == 1
    g = rec.glosses[0]
    assert g.status == "confident" and g.display == "Help" and g.safety_lexicon == "HELP"
