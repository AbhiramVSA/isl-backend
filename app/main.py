from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.v1.router import api_router
from app.core.config import Settings, settings
from app.db.base import Base
from app.db.session import engine

DEV_SECRET_KEY = Settings.model_fields["secret_key"].default


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Importing the models registers every table on Base.metadata.
    # `from app import models` rather than `import app.models` — the latter binds
    # the name `app` in this scope and shadows the FastAPI instance below.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    if settings.secret_key == DEV_SECRET_KEY or len(settings.secret_key) < 32:
        # Anyone who has read the source can mint a token for any account while
        # the default is in use (an empty or short key is little better), so
        # say it loudly rather than only in the README.
        print(
            "[isl-sos] WARNING: SECRET_KEY is the built-in development default "
            "or shorter than 32 characters. Set a random SECRET_KEY in .env "
            "before exposing this service.",
            flush=True,
        )

    # Load the ISL model once at startup. If the legacy CV stack or the
    # model files are missing, keep the API up and report via /health — the
    # rest of the service (reports, auth, stations) does not depend on it.
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
