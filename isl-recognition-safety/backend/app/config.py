"""Application settings (environment variables / .env)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_prefix="ISL_", extra="ignore")

    models_dir: Path = ROOT / "models"
    frontend_dist: Path = ROOT / "frontend" / "dist"

    # Compute
    device: str = "auto"  # auto | cuda | cpu
    hwgat_fp16: bool = True

    # Model toggles (a missing checkpoint disables the head automatically)
    enable_hwgat: bool = True
    enable_include: bool = True
    enable_slgcn: bool = True
    enable_stgcnpp: bool = True

    # Recognition
    window_stride_ms: int = 400        # how often to classify the active segment (GPU)
    window_stride_cpu_ms: int = 1200   # slower cadence when running on CPU
    min_segment_ms: int = 500          # do not classify segments shorter than this
    max_segment_ms: int = 4500         # trailing length of landmarks fed to the heads
    conf_high: float = 0.55            # confident gloss
    conf_low: float = 0.35             # below this the segment is UNKNOWN
    margin_min: float = 0.15
    agree_windows: int = 2
    sentence_rest_ms: int = 1200
    sentence_max_glosses: int = 12

    # Safety
    action_stride_ms: int = 500
    action_min_quality: float = 0.7
    immobile_warn_s: float = 10.0
    long_lie_s: float = 60.0
    event_cooldown_s: float = 30.0

    # Language layer
    llm_provider: str = "none"  # none | anthropic | ollama
    anthropic_model: str = "claude-opus-5"
    ollama_model: str = "qwen2.5:3b"
    ollama_url: str = "http://localhost:11434"
    llm_timeout_s: float = 20.0

    # Uploads
    max_upload_mb: int = 200
    upload_max_width: int = 960
    cors_origins: str = "*"


settings = Settings()
