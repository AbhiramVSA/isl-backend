"""FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import analyze, stream
from .api.state import state
from .config import settings
from .safety.monitor import SAFETY_LEXICON

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.startup()
    h = state.health()
    for k, v in h["models"].items():
        log.info("model %-9s loaded=%s %s", k, v["loaded"], v.get("error") or "")
    log.info("device=%s llm=%s", h["device"], h["llm"])
    yield


app = FastAPI(title="ISL Recognition + Safety Monitor", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(stream.router)
app.include_router(analyze.router)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return state.health()


@app.get("/api/models")
async def models() -> dict[str, Any]:
    reg = state.registry
    out = {k: v.to_json(with_vocab=True) for k, v in reg.infos.items()}
    out["holistic"] = {"name": "MediaPipe HolisticLandmarker", "license": "Apache-2.0",
                       "dataset": "Google internal (BlazePose, hand and face mesh models)",
                       "reported_accuracy": "not published as a single number", "vocab_size": 0, "loaded": reg.holistic_ok,
                       "error": reg.holistic_error, "limitations": "33 pose + 21+21 hand + 478 face landmarks; CPU only in Windows Python; hands must be visible and reasonably large.",
                       "citation": "https://ai.google.dev/edge/mediapipe/solutions/vision/holistic_landmarker"}
    out["safety_lexicon"] = {k: sorted(v) for k, v in SAFETY_LEXICON.items()}
    return out


@app.get("/models/holistic_landmarker.task", include_in_schema=False)
async def holistic_task_file():
    """The browser-side landmarker loads the same MediaPipe model the server uses; serve it from
    frontend/dist if the build copied it there, otherwise straight from the models directory."""
    for cand in (settings.frontend_dist / "models" / "holistic_landmarker.task",
                 settings.models_dir / "mediapipe" / "holistic_landmarker.task"):
        if cand.is_file():
            return FileResponse(cand, media_type="application/octet-stream")
    return JSONResponse({"detail": "holistic_landmarker.task not found; run scripts/download_models.py"}, status_code=404)


# Serve the built frontend if present (production / single-process mode)
dist = settings.frontend_dist
if dist.exists() and (dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    if (dist / "mediapipe-wasm").exists():
        app.mount("/mediapipe-wasm", StaticFiles(directory=dist / "mediapipe-wasm"), name="mediapipe-wasm")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        target = dist / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(dist / "index.html")
else:
    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse({"message": "frontend not built; run `npm run build` in frontend/ or use the Vite dev server",
                             "health": "/api/health"})
