"""Unauthenticated /app live-stream endpoints.

Covers the bridge helpers (validation, throttle, draft accumulation) as pure
unit tests, plus the transport: a fake ISL socket is injected where
``mobile_stream.connect_isl`` is looked up, so no recogniser is needed.
"""

import asyncio
import base64

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.api import mobile_stream
from app.main import app
from app.services import isl_stream
from app.services.isl_stream import (
    DraftAccumulator,
    InboundThrottle,
    StreamLimiter,
    hash_token,
    tokens_match,
    validate_client_message,
)

UPDATE = {
    "type": "update",
    "t_ms": 400.0,
    "vision": {"pose": True},
    "gate": {"state": "ACTIVE"},
    "window": None,
    "glosses": [{"label": "HELP", "display": "help", "p": 0.9, "t_start_ms": 0, "t_end_ms": 400}],
    "sentences": [{"id": "s1", "text": "need help", "glosses": []}],
    "safety": {"status": "ok"},
    "safety_events": [],
}


def landmarks(t_ms: float = 100.0) -> dict:
    return {
        "type": "landmarks",
        "t_ms": t_ms,
        "width": 640,
        "height": 480,
        "pose": [[0.5, 0.5, 0.0, 0.9]] * 33,
        "left_hand": None,
        "right_hand": [[0.5, 0.5, 0.0]] * 21,
        "face": True,
    }


def frame(t_ms: float = 100.0) -> dict:
    return {"type": "frame", "t_ms": t_ms, "jpeg": base64.b64encode(b"fake-jpeg").decode()}


class FakeIsl:
    """Stands in for the recogniser's live socket: hello, then one update."""

    def __init__(self) -> None:
        import json as _json

        self.sent: list[str] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self._queue.put_nowait(_json.dumps({"type": "hello", "session_id": "fake"}))
        self.closed = False

    async def send(self, text: str) -> None:
        import json

        self.sent.append(text)
        msg = json.loads(text)
        if msg.get("type") in {"landmarks", "frame"}:
            update = dict(UPDATE)
            update["t_ms"] = msg.get("t_ms", 0.0)
            self._queue.put_nowait(json.dumps(update))
        elif msg.get("type") == "control" and msg.get("action") == "end_sentence":
            self._queue.put_nowait(json.dumps(dict(UPDATE)))

    async def recv(self):
        return await self._queue.get()

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def portal_client():
    isl_stream.limiter.kind_counts.clear()
    isl_stream.limiter.ip_counts.clear()
    mobile_stream.limiter.kind_counts.clear()
    mobile_stream.limiter.ip_counts.clear()
    with TestClient(app) as portal:
        yield portal
    isl_stream.limiter.kind_counts.clear()
    isl_stream.limiter.ip_counts.clear()
    mobile_stream.limiter.kind_counts.clear()
    mobile_stream.limiter.ip_counts.clear()


# --- validation -------------------------------------------------------------


def test_landmarks_shape_is_checked():
    assert validate_client_message(landmarks(), kind="landmarks", max_frame_bytes=1024)["type"] == (
        "landmarks"
    )
    bad = landmarks()
    bad["pose"] = [[0.5, 0.5]] * 33
    with pytest.raises(ValueError):
        validate_client_message(bad, kind="landmarks", max_frame_bytes=1024)


def test_landmarks_reject_non_finite_and_empty():
    bad = landmarks()
    bad["pose"][0][0] = float("inf")
    with pytest.raises(ValueError):
        validate_client_message(bad, kind="landmarks", max_frame_bytes=1024)
    empty = landmarks()
    empty.update({"pose": None, "left_hand": None, "right_hand": None})
    with pytest.raises(ValueError):
        validate_client_message(empty, kind="landmarks", max_frame_bytes=1024)


def test_video_endpoint_only_takes_frames():
    assert validate_client_message(frame(), kind="video", max_frame_bytes=10_000)["type"] == "frame"
    with pytest.raises(ValueError):
        validate_client_message(landmarks(), kind="video", max_frame_bytes=10_000)
    with pytest.raises(ValueError):
        validate_client_message(
            {"type": "frame", "t_ms": 1.0, "jpeg": "!!!"}, kind="video", max_frame_bytes=10_000
        )


def test_control_actions_are_checked():
    validate_client_message(
        {"type": "control", "action": "reset"}, kind="landmarks", max_frame_bytes=1024
    )
    with pytest.raises(ValueError):
        validate_client_message(
            {"type": "control", "action": "explode"}, kind="landmarks", max_frame_bytes=1024
        )


# --- accumulator / throttle / tokens ----------------------------------------


def test_draft_prefers_sentences_then_glosses():
    acc = DraftAccumulator()
    acc.add_snapshot(
        {
            "t_ms": 100.0,
            "sentences": [{"id": "s1", "text": "need help"}],
            "glosses": [],
            "safety_events": [],
        }
    )
    assert acc.transcript == "need help"
    assert acc.duration_ms == 0
    acc.add_snapshot(
        {
            "t_ms": 500.0,
            "sentences": [{"id": "s1", "text": "need help"}],
            "glosses": [],
            "safety_events": [],
        }
    )
    assert acc.duration_ms == 400
    bare = DraftAccumulator()
    bare.add_snapshot(
        {
            "t_ms": 1.0,
            "sentences": [],
            "glosses": [{"label": "HELP", "display": "help"}],
            "safety_events": [],
        }
    )
    assert bare.transcript == "help"


def test_throttle_drops_over_rate_frames():
    throttle = InboundThrottle(max_fps=10.0)
    assert throttle.allow(now=0.0)
    assert not throttle.allow(now=0.01)
    assert throttle.allow(now=0.2)
    assert throttle.dropped == 1


def test_draft_tokens_verify():
    token = isl_stream.new_draft_token()
    assert tokens_match(token, hash_token(token))
    assert not tokens_match(token + "x", hash_token(token))


async def test_limiter_caps_a_kind():
    limiter = StreamLimiter()
    assert await limiter.acquire("landmarks", "1.2.3.4", kind_max=1, ip_max=5)
    assert not await limiter.acquire("landmarks", "5.6.7.8", kind_max=1, ip_max=5)
    await limiter.release("landmarks", "1.2.3.4")
    assert await limiter.acquire("landmarks", "5.6.7.8", kind_max=1, ip_max=5)
    await limiter.release("landmarks", "5.6.7.8")


# --- transport --------------------------------------------------------------


async def test_landmarks_stream_returns_live_updates_and_a_draft(
    portal_client, monkeypatch, client
):
    fake = FakeIsl()

    async def fake_connect(url, *, timeout, max_size=0):
        assert url  # wired to settings.isl_ws_url
        return fake

    monkeypatch.setattr(mobile_stream, "connect_isl", fake_connect)
    with portal_client.websocket_connect("/app/api/v1/stream/landmarks") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["stream_id"] and hello["draft_token"]
        ws.send_json(landmarks())
        update = ws.receive_json()
        assert update["type"] == "update"
        assert update["sentences"][0]["text"] == "need help"

    stream_id, token = hello["stream_id"], hello["draft_token"]
    for _ in range(100):
        response = await client.get(f"/app/api/v1/stream/{stream_id}/draft?token={token}")
        if response.status_code == 200 and response.json()["completed"]:
            break
        await asyncio.sleep(0.05)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transcript"] == "need help"
    assert body["kind"] == "landmarks"
    assert body["frames_seen"] >= 1


async def test_wrong_draft_token_is_indistinguishable_from_missing(
    portal_client, monkeypatch, client
):
    fake = FakeIsl()

    async def fake_connect(url, *, timeout, max_size=0):
        return fake

    monkeypatch.setattr(mobile_stream, "connect_isl", fake_connect)
    with portal_client.websocket_connect("/app/api/v1/stream/landmarks") as ws:
        hello = ws.receive_json()

    wrong = await client.get(f"/app/api/v1/stream/{hello['stream_id']}/draft?token=nope")
    missing = await client.get("/app/api/v1/stream/doesnotexist/draft?token=nope")
    assert wrong.status_code == 404
    assert missing.status_code == 404


async def test_wrong_kind_message_stays_open_with_an_error(portal_client, monkeypatch):
    fake = FakeIsl()

    async def fake_connect(url, *, timeout, max_size=0):
        return fake

    monkeypatch.setattr(mobile_stream, "connect_isl", fake_connect)
    with portal_client.websocket_connect("/app/api/v1/stream/video") as ws:
        ws.receive_json()  # hello
        ws.send_json(landmarks())  # landmarks on the video socket
        error = ws.receive_json()
        assert error["type"] == "error"
        ws.send_json(frame())  # socket still usable
        update = ws.receive_json()
        assert update["type"] == "update"


async def test_recogniser_outage_points_at_clip_upload(portal_client, monkeypatch):
    async def failing_connect(url, *, timeout, max_size=0):
        raise OSError("connection refused")

    monkeypatch.setattr(mobile_stream, "connect_isl", failing_connect)
    with portal_client.websocket_connect("/app/api/v1/stream/landmarks") as ws:
        assert ws.receive_json()["type"] == "hello"
        error = ws.receive_json()
        assert error["fallback"] == "/app/api/v1/predict"
        try:
            ws.receive_json()
            raise AssertionError("expected the socket to close")
        except WebSocketDisconnect as exc:
            assert exc.code == 4403


async def test_full_house_is_turned_away(portal_client, monkeypatch):
    monkeypatch.setattr(mobile_stream.settings, "stream_max_landmark_streams", 0)
    try:
        with portal_client.websocket_connect("/app/api/v1/stream/landmarks"):
            raise AssertionError("expected the socket to be refused")
    except WebSocketDisconnect as exc:
        assert exc.code == 4409


async def test_unknown_draft_is_404(client):
    response = await client.get("/app/api/v1/stream/doesnotexist/draft?token=x")
    assert response.status_code == 404
