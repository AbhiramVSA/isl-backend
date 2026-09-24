from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Incident Response"
    environment: str = "development"
    secret_key: str = "development-only-change-me"
    database_url: str = "sqlite+aiosqlite:///./incident.db"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    cors_origins: str = "http://localhost:5173"
    upload_dir: Path = Path("uploads")
    max_upload_bytes: int = 25 * 1024 * 1024
    livekit_url: str = "ws://localhost:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "secret"
    recording_dir: Path = Path("recordings")
    development_global_officer_queue: bool = True

    # Recognition backend points at the isl-recognition-safety service.
    isl_recognition_url: str = "http://isl:8000"
    isl_recognition_timeout_seconds: float = 180.0
    isl_recognition_poll_seconds: float = 0.5

    # --- Equal mobile app live streaming --------------------------------------
    # The /app clip endpoint (POST /app/api/v1/predict) uploads a finished
    # file and waits for a batch job. The streaming endpoints below instead
    # bridge a phone-side WebSocket to the recognition service's own live
    # socket, so glosses arrive while the user is still signing.
    # Explicit URL (rather than deriving from isl_recognition_url) so tests
    # and single-process deployments can point the bridge at a fake server.
    isl_ws_url: str = "ws://isl:8000/ws/stream"
    isl_stream_connect_timeout_seconds: float = 8.0
    # Unauthenticated by design (like /predict: record before login), so the
    # caps below — not identity — are the abuse control. Separate budgets:
    # landmarks JSON is cheap, server-side JPEG decode is CPU-hot.
    stream_max_landmark_streams: int = 50
    stream_max_video_streams: int = 10
    stream_max_streams_per_ip: int = 2
    stream_max_in_fps_landmarks: float = 15.0
    stream_max_in_fps_video: float = 10.0
    stream_max_message_bytes_landmarks: int = 256 * 1024
    stream_max_message_bytes_video: int = 512 * 1024
    stream_max_minutes: float = 10.0
    stream_max_bytes_mb: float = 200.0
    stream_idle_seconds: float = 30.0
    stream_draft_ttl_hours: float = 24.0

    # --- Equal mobile app ---------------------------------------------------
    # The console rotates a 15-minute token against /auth/refresh. The app holds
    # a single token and has no refresh flow, so it gets a long-lived one rather
    # than signing someone out in the middle of an emergency.
    mobile_access_token_days: int = 30
    # Set to hold the NIM key server-side; without it /api/v1/llm/chat answers
    # 503 and the app goes on calling NIM directly with its bundled key.
    nvidia_nim_api_key: str = ""
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nim_default_model: str = "meta/muse-glimmer-30b"
    nim_timeout_seconds: float = 120.0
    auth_requests_per_minute: int = 30
    read_requests_per_minute: int = 1200
    write_requests_per_minute: int = 240
    allowed_media_types: set[str] = Field(
        default={"image/jpeg", "image/png", "image/webp", "video/mp4", "video/webm"}
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
