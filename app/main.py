from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.v1.router import api_router
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the ISL model once at startup. If the legacy CV stack or the
    # model files are missing, keep the API up and report via /health.
    app.state.recognizer = None
    app.state.recognizer_error = None
    try:
        from app.services.isl import ISLRecognizer

        app.state.recognizer = ISLRecognizer(settings.lstm_weights_path)
    except Exception as exc:
        app.state.recognizer_error = str(exc)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router, tags=["health"])
app.include_router(api_router, prefix=settings.api_v1_prefix)
