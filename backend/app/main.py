import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    admin,
    auth,
    mobile,
    officer_reports,
    offices,
    reports,
    streams,
    transcription,
    websocket,
)
from app.core.config import settings
from app.db import Base, engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.recording_dir.mkdir(parents=True, exist_ok=True)
    if settings.environment == "test":
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="Incident Response API",
    version="1.0.0",
    description="Secure mobile reporting and officer response API. All report access is scoped to the signed-in user or responsible office.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

rate_windows: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def security_and_rate_limit(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path == "/health":
        return await call_next(request)
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{request.method}:{request.url.path}"
    now = time.monotonic()
    window = rate_windows[key]
    while window and window[0] < now - 60:
        window.popleft()
    if "/auth/" in request.url.path:
        limit = settings.auth_requests_per_minute
    elif request.method in {"GET", "HEAD"}:
        limit = settings.read_requests_per_minute
    else:
        limit = settings.write_requests_per_minute
    if len(window) >= limit:
        return JSONResponse(
            status_code=429,
            content={"detail": "The dashboard is updating too quickly. Please try again in a moment."},
            headers={"Retry-After": "2"},
        )
    window.append(now)
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(max(0, limit - len(window)))
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(self), geolocation=(self), microphone=(self)"
    return response


@app.exception_handler(Exception)
async def unexpected_error(_request: Request, _exc: Exception):
    return JSONResponse(
        status_code=500, content={"detail": "Something went wrong. Please try again."}
    )


for api_router in (
    auth.router,
    reports.router,
    officer_reports.router,
    offices.router,
    streams.router,
    transcription.router,
    admin.router,
    websocket.router,
):
    app.include_router(api_router, prefix="/api/v1")

# The Equal mobile app, mounted away from the routes above. It asks for
# POST /reports, GET /reports/{id} and GET /auth/me too, in incompatible shapes
# — different id types, a five-value status against seven — so sharing paths
# would mean breaking one client to serve the other. The app's base address is
# runtime configuration, so pointing it at https://host/app costs nothing.
app.include_router(mobile.router, prefix="/app")


@app.get("/health", tags=["Operations"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
