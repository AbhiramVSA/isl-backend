"""Responders watching, rewinding and receiving Equal app camera streams."""

import asyncio
import time
import uuid
from datetime import UTC, datetime

import pytest
from conftest import auth
from sqlalchemy import select
from test_mobile_stream import FakeIsl, frame, portal_client  # noqa: F401
from test_roles import login, roster

from app.api import mobile_stream
from app.core.config import settings
from app.models import Report
from app.services import live_relay
from app.services.live_relay import live_hub, recording_key


@pytest.fixture(autouse=True)
def media_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "recording_dir", tmp_path / "recordings")
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    live_hub.sessions.clear()

    def fake_build(session):
        # ffmpeg is not needed to test the plumbing around it.
        out = settings.upload_dir / recording_key(session.stream_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mp4")
        return True

    monkeypatch.setattr(live_relay, "build_mp4", fake_build)
    yield
    live_hub.sessions.clear()


async def caller_token(client) -> str:
    body = {"identifier": "caller@test.dev", "passcode": "2468"}
    await client.post("/app/api/v1/auth/register", json=body)
    response = await client.post("/app/api/v1/auth/login", json=body)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def stream_frames(portal, monkeypatch, token: str | None, count: int = 3) -> dict:
    fake = FakeIsl()

    async def fake_connect(url, *, timeout, max_size=0):
        return fake

    monkeypatch.setattr(mobile_stream, "connect_isl", fake_connect)
    url = "/app/api/v1/stream/video" + (f"?access_token={token}" if token else "")
    with portal.websocket_connect(url) as ws:
        hello = ws.receive_json()
        for index in range(count):
            if index:
                time.sleep(0.15)  # stay under the 10 fps inbound cap, like a phone
            ws.send_json(frame(1000.0 + index * 200))
            assert ws.receive_json()["type"] == "update"
    return hello


async def console_id(db, reference_code: str) -> str:
    """The app knows a report by its reference; the console by its public id."""
    return await db.scalar(select(Report.public_id).where(Report.reference_code == reference_code))


async def wait_for(predicate, timeout=5.0):
    for _ in range(int(timeout / 0.05)):
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_stream_is_recorded_listed_and_rewindable(portal_client, monkeypatch, client, db):  # noqa: F811
    await roster(db)
    hello = stream_frames(portal_client, monkeypatch, await caller_token(client))
    stream_id = hello["stream_id"]
    assert await wait_for(
        lambda: live_hub.get(stream_id) and live_hub.get(stream_id).recording_ready
    )

    officer = auth(await login(client, "officer"))
    listing = (await client.get("/api/v1/officer/live", headers=officer)).json()
    entry = next(item for item in listing if item["stream_id"] == stream_id)
    assert entry["frames"] == 3
    assert entry["reporter_name"]  # the signed-in caller, not "anonymous"
    assert entry["caption"] == "help" and entry["transcript"] == "need help"
    assert entry["live"] is False and entry["report_id"] is None

    segment = (
        await client.get(
            f"/api/v1/officer/live/{stream_id}/segment?start_ms=0&duration_ms=10000",
            headers=officer,
        )
    ).json()
    assert [f["t_ms"] for f in segment["frames"]] == [0.0, 200.0, 400.0]

    # Callers cannot read the responder endpoints.
    caller = auth(await caller_token(client))
    assert (await client.get("/api/v1/officer/live", headers=caller)).status_code == 403


async def test_discarded_recording_is_deleted(portal_client, monkeypatch, client, db):  # noqa: F811
    await roster(db)
    hello = stream_frames(portal_client, monkeypatch, None)
    stream_id, token = hello["stream_id"], hello["draft_token"]
    assert await wait_for(
        lambda: live_hub.get(stream_id) and live_hub.get(stream_id).recording_ready
    )
    frames_dir = settings.recording_dir / "streams" / stream_id
    video = settings.upload_dir / recording_key(stream_id)
    assert frames_dir.is_dir() and video.is_file()

    wrong = await client.delete(f"/app/api/v1/stream/{stream_id}?token=nope")
    assert wrong.status_code == 404
    gone = await client.delete(f"/app/api/v1/stream/{stream_id}?token={token}")
    assert gone.status_code == 204
    assert not frames_dir.exists() and not video.exists()
    assert live_hub.get(stream_id) is None
    draft = await client.get(f"/app/api/v1/stream/{stream_id}/draft?token={token}")
    assert draft.status_code == 404


async def test_filed_report_gets_the_video_and_cannot_be_discarded(
    portal_client,  # noqa: F811
    monkeypatch,
    client,
    db,
):
    await roster(db)
    token = await caller_token(client)
    hello = stream_frames(portal_client, monkeypatch, token)
    stream_id, draft_token = hello["stream_id"], hello["draft_token"]
    assert await wait_for(
        lambda: live_hub.get(stream_id) and live_hub.get(stream_id).recording_ready
    )

    filed = await client.post(
        "/app/api/v1/reports",
        headers=auth(token),
        json={
            "client_id": str(uuid.uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
            "title": "Help needed",
            "category": "MedicalEmergency",
            "severity": "High",
            "summary": "Caller signed for help.",
            "situation_analysis": "Signed on a live stream.",
            "transcript": "need help",
            "latitude": 16.506,
            "longitude": 80.648,
            "stream_id": stream_id,
            "stream_token": draft_token,
        },
    )
    assert filed.status_code == 201, filed.text
    report_id = await console_id(db, filed.json()["reference_code"])

    officer = auth(await login(client, "officer"))
    videos = (
        await client.get(f"/api/v1/officer/reports/{report_id}/videos", headers=officer)
    ).json()
    assert len(videos) == 1 and videos[0]["label"] == "Signing video from the Equal app"
    linked = (await client.get(f"/api/v1/officer/reports/{report_id}/live", headers=officer)).json()
    assert linked["stream_id"] == stream_id and linked["report_id"] == report_id

    refused = await client.delete(f"/app/api/v1/stream/{stream_id}?token={draft_token}")
    assert refused.status_code == 409
    assert (settings.upload_dir / recording_key(stream_id)).is_file()


async def test_someone_elses_stream_cannot_be_claimed(portal_client, monkeypatch, client, db):  # noqa: F811
    await roster(db)
    hello = stream_frames(portal_client, monkeypatch, None)
    token = await caller_token(client)
    filed = await client.post(
        "/app/api/v1/reports",
        headers=auth(token),
        json={
            "client_id": str(uuid.uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
            "title": "Help",
            "category": "Unknown",
            "severity": "Low",
            "summary": "s",
            "situation_analysis": "s",
            "stream_id": hello["stream_id"],
            "stream_token": "guessed",
        },
    )
    assert filed.status_code == 201
    report_id = await console_id(db, filed.json()["reference_code"])
    officer = auth(await login(client, "officer"))
    videos = (
        await client.get(f"/api/v1/officer/reports/{report_id}/videos", headers=officer)
    ).json()
    assert videos == []


def motion(t_ms: float, *, a=(0.1, 0.2, 0.1), g=(0.0, 0.1, 0.0)) -> dict:
    return {"t_ms": t_ms, "q": [0.0, 0.0, 0.0, 1.0], "a": list(a), "g": list(g)}


async def test_phone_motion_is_recorded_with_events_and_kept_with_the_report(
    portal_client,  # noqa: F811
    monkeypatch,
    client,
    db,
):
    await roster(db)
    token = await caller_token(client)
    fake = FakeIsl()

    async def fake_connect(url, *, timeout, max_size=0):
        return fake

    monkeypatch.setattr(mobile_stream, "connect_isl", fake_connect)
    with portal_client.websocket_connect(f"/app/api/v1/stream/video?access_token={token}") as ws:
        hello = ws.receive_json()
        ws.send_json(frame(1000.0))
        assert ws.receive_json()["type"] == "update"
        ws.send_json(
            {
                "type": "motion",
                "samples": [motion(1033.0), motion(1066.0, a=(0.0, 30.0, 0.0)), motion(1100.0)],
            }
        )
        # Out-of-range values are refused without ending the stream.
        ws.send_json({"type": "motion", "samples": [motion(1133.0, a=(0.0, 999.0, 0.0))]})
        assert ws.receive_json()["type"] == "error"
        time.sleep(0.15)
        ws.send_json(frame(1200.0))
        assert ws.receive_json()["type"] == "update"
    stream_id, draft_token = hello["stream_id"], hello["draft_token"]
    # The sign model never sees phone motion.
    assert all('"motion"' not in sent for sent in fake.sent)

    officer = auth(await login(client, "officer"))
    track = (await client.get(f"/api/v1/officer/live/{stream_id}/motion", headers=officer)).json()
    assert [s["t_ms"] for s in track["samples"]] == [33.0, 66.0, 100.0]
    assert [e["kind"] for e in track["events"]] == ["impact"]
    assert track["events"][0]["t_ms"] == 66.0

    assert await wait_for(
        lambda: live_hub.get(stream_id) and live_hub.get(stream_id).recording_ready
    )
    saved = settings.upload_dir / live_relay.motion_key(stream_id)
    assert saved.is_file()

    filed = await client.post(
        "/app/api/v1/reports",
        headers=auth(token),
        json={
            "client_id": str(uuid.uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
            "title": "Help",
            "category": "Violence",
            "severity": "High",
            "summary": "s",
            "situation_analysis": "s",
            "stream_id": stream_id,
            "stream_token": draft_token,
        },
    )
    report_id = await console_id(db, filed.json()["reference_code"])
    live_hub.sessions.clear()  # after the live list forgets it, the saved file answers
    from_file = (
        await client.get(f"/api/v1/officer/reports/{report_id}/motion", headers=officer)
    ).json()
    assert len(from_file["samples"]) == 3 and from_file["events"][0]["kind"] == "impact"


async def test_discard_removes_the_motion_track(portal_client, monkeypatch, client, db):  # noqa: F811
    await roster(db)
    fake = FakeIsl()

    async def fake_connect(url, *, timeout, max_size=0):
        return fake

    monkeypatch.setattr(mobile_stream, "connect_isl", fake_connect)
    with portal_client.websocket_connect("/app/api/v1/stream/video") as ws:
        hello = ws.receive_json()
        ws.send_json(frame(1000.0))
        ws.receive_json()
        ws.send_json({"type": "motion", "samples": [motion(1010.0)]})
        time.sleep(0.15)
        ws.send_json(frame(1200.0))
        ws.receive_json()
    stream_id = hello["stream_id"]
    assert await wait_for(
        lambda: live_hub.get(stream_id) and live_hub.get(stream_id).recording_ready
    )
    saved = settings.upload_dir / live_relay.motion_key(stream_id)
    assert saved.is_file()
    response = await client.delete(f"/app/api/v1/stream/{stream_id}?token={hello['draft_token']}")
    assert response.status_code == 204
    assert not saved.exists()
