"""Live relay of Equal app camera streams to the responder console.

The phone already sends JPEG frames to ``WS /app/api/v1/stream/video`` for live
captions. This module taps that stream so responders can watch it:

* every frame is written to disk under ``recording_dir/streams/<id>/`` with its
  timestamp, which is what makes rewinding possible (any moment of the stream
  can be fetched by time, like a DVR);
* frames and caption updates fan out to console viewers over a websocket;
* when the stream ends the frames are stitched into an MP4 with ffmpeg, kept
  at the phone's real timing, and attached to the report once it is filed.

The relay never blocks the recognition path: a slow viewer is dropped, a
failed disk write is logged, and nothing here can end the phone's stream.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import bisect
import contextlib
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi import WebSocket

from app.core.config import settings

log = logging.getLogger(__name__)

# How long an ended stream stays listed (and rewindable) before it is dropped
# from memory. The frames and MP4 stay on disk.
ENDED_RETENTION_SECONDS = 15 * 60


def streams_dir() -> Path:
    return settings.recording_dir / "streams"


def motion_key(stream_id: str) -> str:
    """Path of the saved motion track, relative to ``upload_dir`` (next to the MP4)."""
    return f"streams/{stream_id}.motion.json"


# Motion events worth a responder's attention. Thresholds are deliberately
# conservative: a phone in a pocket or hand jostles constantly.
IMPACT_MS2 = 25.0  # linear acceleration spike (~2.5 g) — dropped, hit, thrown
JOLT_MS2 = 15.0  # sharp movement
SHAKE_RADS = 8.0  # sustained fast rotation — struggle or violent shaking
SHAKE_SUSTAIN_MS = 300
EVENT_COOLDOWN_MS = 2000
EVENT_LABELS = {
    "impact": "Hard impact — phone may have been dropped or hit",
    "jolt": "Sudden movement",
    "shaking": "Violent shaking",
}


def _magnitude(values: list[float]) -> float:
    return sum(v * v for v in values) ** 0.5


def recording_key(stream_id: str) -> str:
    """Path of the finished MP4, relative to ``upload_dir`` (served like any report video)."""
    return f"streams/{stream_id}.mp4"


@dataclass
class LiveSession:
    stream_id: str
    started_at: datetime
    user_id: int | None = None
    reporter_name: str | None = None
    # Frame timeline: t_ms relative to the first frame, and the file it lives in.
    times: list[float] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    first_t: float | None = None
    caption: str = ""
    transcript: str = ""
    safety: str = "ok"
    ended_at: datetime | None = None
    report_public_id: str | None = None
    recording_ready: bool = False
    viewers: set[WebSocket] = field(default_factory=set)
    latest_jpeg: str | None = None
    discarded: bool = False
    # Phone motion on the same timeline as the frames: (t_ms, q, a, g).
    motion: list[tuple[float, list[float], list[float], list[float]]] = field(default_factory=list)
    motion_events: list[dict] = field(default_factory=list)
    _shake_since: float | None = None
    _last_event: dict = field(default_factory=dict)

    @property
    def live(self) -> bool:
        return self.ended_at is None

    @property
    def duration_ms(self) -> float:
        return self.times[-1] if self.times else 0.0

    def summary(self) -> dict:
        return {
            "stream_id": self.stream_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "live": self.live,
            "duration_ms": round(self.duration_ms),
            "frames": len(self.times),
            "reporter_name": self.reporter_name,
            "caption": self.caption,
            "transcript": self.transcript,
            "safety": self.safety,
            "report_id": self.report_public_id,
            "recording_ready": self.recording_ready,
            "motion": bool(self.motion),
            "motion_events": len(self.motion_events),
        }

    def motion_track(self) -> dict:
        return {
            "duration_ms": round(self.duration_ms),
            "samples": [
                {"t_ms": round(t, 1), "q": q, "a": a, "g": g} for t, q, a, g in self.motion
            ],
            "events": self.motion_events,
        }


class LiveHub:
    def __init__(self) -> None:
        self.sessions: dict[str, LiveSession] = {}
        # Strong references so finishing tasks are not garbage collected mid-run.
        self._tasks: set[asyncio.Task] = set()

    # --- phone side ---------------------------------------------------------

    def start(self, stream_id: str, user_id: int | None, reporter_name: str | None) -> LiveSession:
        self._prune()
        session = LiveSession(
            stream_id=stream_id,
            started_at=datetime.now(UTC),
            user_id=user_id,
            reporter_name=reporter_name,
        )
        (streams_dir() / stream_id).mkdir(parents=True, exist_ok=True)
        self.sessions[stream_id] = session
        self._announce({"type": "live.started", **session.summary()})
        return session

    async def push_frame(self, session: LiveSession, t_ms: float, jpeg_b64: str) -> None:
        if session.discarded:
            return
        try:
            data = base64.b64decode(jpeg_b64, validate=True)
        except (binascii.Error, ValueError):
            return
        if session.first_t is None:
            session.first_t = t_ms
        rel = max(0.0, t_ms - session.first_t)
        if session.times and rel <= session.times[-1]:
            rel = session.times[-1] + 1  # keep the timeline strictly increasing
        name = f"{len(session.times):06d}.jpg"
        try:
            (streams_dir() / session.stream_id / name).write_bytes(data)
        except OSError:
            log.exception("live %s: frame write failed", session.stream_id)
            return
        session.times.append(rel)
        session.files.append(name)
        session.latest_jpeg = jpeg_b64
        await self._broadcast(session, {"type": "frame", "t_ms": rel, "jpeg": jpeg_b64})

    async def push_motion(self, session: LiveSession, samples: list[dict]) -> None:
        if session.discarded:
            return
        out = []
        for sample in samples:
            if session.first_t is None:
                session.first_t = sample["t_ms"]
            rel = max(0.0, sample["t_ms"] - session.first_t)
            q = [round(v, 4) for v in sample["q"]]
            a = [round(v, 3) for v in sample["a"]]
            g = [round(v, 3) for v in sample["g"]]
            session.motion.append((rel, q, a, g))
            out.append({"t_ms": round(rel, 1), "q": q, "a": a, "g": g})
            for event in self._detect(session, rel, a, g):
                session.motion_events.append(event)
                await self._broadcast(session, {"type": "motion.event", **event})
        await self._broadcast(session, {"type": "motion", "samples": out})

    def _detect(self, session: LiveSession, t: float, a: list[float], g: list[float]) -> list[dict]:
        found = []
        accel, spin = _magnitude(a), _magnitude(g)
        if accel >= IMPACT_MS2:
            found.append(("impact", accel))
        elif accel >= JOLT_MS2:
            found.append(("jolt", accel))
        if spin >= SHAKE_RADS:
            session._shake_since = t if session._shake_since is None else session._shake_since
            if t - session._shake_since >= SHAKE_SUSTAIN_MS:
                found.append(("shaking", spin))
        else:
            session._shake_since = None
        events = []
        for kind, value in found:
            if t - session._last_event.get(kind, -EVENT_COOLDOWN_MS) < EVENT_COOLDOWN_MS:
                continue
            session._last_event[kind] = t
            events.append(
                {
                    "t_ms": round(t, 1),
                    "kind": kind,
                    "label": EVENT_LABELS[kind],
                    "value": round(value, 1),
                }
            )
        return events

    async def push_update(self, session: LiveSession, update: dict) -> None:
        glosses = update.get("glosses") or []
        if glosses and isinstance(glosses[-1], dict):
            session.caption = str(glosses[-1].get("display") or glosses[-1].get("label") or "")
        sentences = update.get("sentences") or []
        texts = [str(s.get("text", "")) for s in sentences if isinstance(s, dict) and s.get("text")]
        if texts:
            session.transcript = " ".join(texts)
        safety = update.get("safety")
        if isinstance(safety, dict) and safety.get("status"):
            session.safety = str(safety["status"])
        await self._broadcast(
            session,
            {
                "type": "caption",
                "t_ms": session.duration_ms,
                "caption": session.caption,
                "transcript": session.transcript,
                "safety": session.safety,
            },
        )

    def finish(self, session: LiveSession) -> None:
        if session.ended_at:
            return
        session.ended_at = datetime.now(UTC)
        task = asyncio.get_running_loop().create_task(self._finish(session))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _finish(self, session: LiveSession) -> None:
        await self._broadcast(session, {"type": "ended", **session.summary()})
        self._announce({"type": "live.ended", **session.summary()})
        if session.motion and not session.discarded:
            path = settings.upload_dir / motion_key(session.stream_id)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(session.motion_track()))
            except OSError:
                log.exception("live %s: motion track write failed", session.stream_id)
        if session.times and not session.discarded:
            ok = await asyncio.to_thread(build_mp4, session)
            if session.discarded:  # thrown away while encoding
                (settings.upload_dir / recording_key(session.stream_id)).unlink(missing_ok=True)
                return
            session.recording_ready = ok
            if ok:
                from app.services.stream_media import attach_recording_if_linked

                await attach_recording_if_linked(session.stream_id)
        await self._broadcast(session, {"type": "recording", "ready": session.recording_ready})

    # --- console side -------------------------------------------------------

    def get(self, stream_id: str) -> LiveSession | None:
        return self.sessions.get(stream_id)

    def listing(self) -> list[dict]:
        self._prune()
        return [
            s.summary()
            for s in sorted(self.sessions.values(), key=lambda s: s.started_at, reverse=True)
        ]

    def segment(self, session: LiveSession, start_ms: float, duration_ms: float) -> list[dict]:
        """Frames in ``[start_ms, start_ms + duration_ms)`` plus the one before start."""
        lo = max(0, bisect.bisect_right(session.times, start_ms) - 1)
        hi = bisect.bisect_left(session.times, start_ms + duration_ms)
        frames = []
        folder = streams_dir() / session.stream_id
        for index in range(lo, min(hi, lo + 200)):
            try:
                data = (folder / session.files[index]).read_bytes()
            except OSError:
                continue
            frames.append(
                {"t_ms": session.times[index], "jpeg": base64.b64encode(data).decode("ascii")}
            )
        return frames

    async def add_viewer(self, session: LiveSession, websocket: WebSocket) -> None:
        session.viewers.add(websocket)
        await websocket.send_json({"type": "meta", **session.summary()})
        if session.latest_jpeg:
            await websocket.send_json(
                {"type": "frame", "t_ms": session.duration_ms, "jpeg": session.latest_jpeg}
            )

    def remove_viewer(self, session: LiveSession, websocket: WebSocket) -> None:
        session.viewers.discard(websocket)

    async def discard(self, stream_id: str) -> None:
        """The caller threw this recording away: viewers are told, then it is forgotten."""
        session = self.sessions.pop(stream_id, None)
        if session is None:
            return
        session.discarded = True
        await self._broadcast(session, {"type": "discarded", "stream_id": stream_id})
        for viewer in tuple(session.viewers):
            with contextlib.suppress(Exception):
                await viewer.close(code=4410)
        self._announce({"type": "live.discarded", "stream_id": stream_id})

    def link_report(self, stream_id: str, public_id: str) -> None:
        session = self.sessions.get(stream_id)
        if session:
            session.report_public_id = public_id
            self._announce({"type": "live.linked", **session.summary()})

    # --- internals ----------------------------------------------------------

    async def _broadcast(self, session: LiveSession, message: dict) -> None:
        if not session.viewers:
            return
        text = json.dumps(message)
        stale = []
        for viewer in tuple(session.viewers):
            try:
                # A viewer that cannot keep up within 1 s is dropped, never waited on.
                await asyncio.wait_for(viewer.send_text(text), timeout=1.0)
            except Exception:
                stale.append(viewer)
        for viewer in stale:
            session.viewers.discard(viewer)

    def _announce(self, message: dict) -> None:
        """Tell every open console (over ``/ws/officer``) that a stream started or ended."""
        from app.services.realtime import realtime_hub

        with contextlib.suppress(RuntimeError):
            task = asyncio.get_running_loop().create_task(realtime_hub.staff_event(message))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _prune(self) -> None:
        now = datetime.now(UTC)
        for stream_id, session in list(self.sessions.items()):
            if (
                session.ended_at
                and (now - session.ended_at).total_seconds() > ENDED_RETENTION_SECONDS
                and not session.viewers
            ):
                del self.sessions[stream_id]


def build_mp4(session: LiveSession) -> bool:
    """Stitch the stream's JPEGs into an H.264 MP4 at their real timing."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log.warning("live %s: ffmpeg not found; recording not built", session.stream_id)
        return False
    folder = streams_dir() / session.stream_id
    lines = ["ffconcat version 1.0"]
    for index, name in enumerate(session.files):
        nxt = session.times[index + 1] if index + 1 < len(session.times) else None
        duration = ((nxt - session.times[index]) / 1000) if nxt is not None else 0.1
        lines.append(f"file '{name}'")
        lines.append(f"duration {max(duration, 0.01):.3f}")
    lines.append(f"file '{session.files[-1]}'")  # concat demuxer needs the last file twice
    (folder / "frames.ffconcat").write_text("\n".join(lines))
    output = settings.upload_dir / recording_key(session.stream_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(folder / "frames.ffconcat"),
        # Phone JPEGs are full-range (yuvj420p); browsers want limited-range 4:2:0 Main.
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2:out_range=tv,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-profile:v", "main", "-pix_fmt", "yuv420p", "-color_range", "tv",
        "-fps_mode", "vfr", "-movflags", "+faststart",
        str(output),
    ]  # fmt: skip
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=300)
    except (subprocess.SubprocessError, OSError) as exc:
        log.error("live %s: ffmpeg failed: %s", session.stream_id, exc)
        return False
    return output.is_file()


live_hub = LiveHub()
