from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=100_000)


class ChatCompletionRequest(BaseModel):
    """The OpenAI-shaped body the app already sends NVIDIA NIM directly.

    Kept identical so moving the app onto this proxy is a base-URL change and
    nothing else.
    """

    model: str | None = None
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1_200, ge=1, le=8_192)
    response_format: dict[str, Any] | None = None
    # Streaming is rejected rather than silently ignored — the app waits for a
    # whole response and would hang on an SSE body.
    stream: bool = False
