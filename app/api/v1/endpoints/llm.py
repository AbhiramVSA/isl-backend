import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.config import settings
from app.models import User
from app.schemas.llm import ChatCompletionRequest

router = APIRouter()


@router.post("/llm/chat")
async def llm_chat(
    payload: ChatCompletionRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """Proxies a chat completion to NVIDIA NIM.

    This exists so the `nvapi-…` key lives on the server instead of inside the
    app binary, where anyone can unzip the APK and read it. The request and
    response are passed through unchanged, so pointing the app here is a
    base-URL change and nothing else.
    """
    if not settings.nvidia_nim_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is not configured on this server.",
        )

    if payload.stream:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Streaming responses are not supported by this proxy.",
        )

    body = payload.model_dump(exclude_none=True)
    body["model"] = payload.model or settings.nim_default_model
    body["stream"] = False

    url = f"{settings.nim_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.nvidia_nim_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.nim_timeout_seconds) as client:
            upstream = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach the language model: {exc}",
        ) from exc

    if upstream.status_code >= 400:
        # Surface upstream's own message, but never the key or our headers.
        detail = upstream.text[:500] or "The language model rejected the request."
        raise HTTPException(status_code=upstream.status_code, detail=detail)

    return upstream.json()
