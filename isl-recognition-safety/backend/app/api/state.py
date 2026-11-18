"""Process-wide singletons (model registry, LLM polisher, analysis jobs)."""
from __future__ import annotations

import logging
import platform
from typing import Any

from ..config import settings
from ..language.llm import LLMPolisher
from ..models.registry import ModelRegistry

log = logging.getLogger(__name__)


class AppState:
    def __init__(self) -> None:
        self.registry = ModelRegistry()
        self.polisher: LLMPolisher | None = None
        self.jobs: dict[str, Any] = {}
        self.versions: dict[str, str] = {}

    def startup(self) -> None:
        import torch
        self.registry.load_all()
        try:
            self.polisher = LLMPolisher()
            if self.polisher.provider != "none":
                log.info("LLM provider %s available=%s error=%s", self.polisher.provider, self.polisher.available, self.polisher.error)
        except Exception as e:  # noqa: BLE001
            log.exception("LLM polisher init failed")
            self.polisher = None
        mp_ver = "n/a"
        try:
            import mediapipe
            mp_ver = mediapipe.__version__
        except Exception:  # noqa: BLE001
            pass
        self.versions = {"torch": torch.__version__, "mediapipe": mp_ver, "python": platform.python_version()}

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "device": self.registry.device.type, **self.versions,
                "models": self.registry.health(),
                "llm": self.polisher.status() if self.polisher else {"provider": "none", "available": False, "model": None, "error": None},
                "settings": {"window_stride_ms": settings.window_stride_ms, "conf_high": settings.conf_high,
                             "conf_low": settings.conf_low, "sentence_rest_ms": settings.sentence_rest_ms}}


state = AppState()
