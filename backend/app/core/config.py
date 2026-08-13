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
