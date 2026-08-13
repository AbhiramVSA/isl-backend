from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request):
    return {
        "status": "ok",
        "model_loaded": request.app.state.recognizer is not None,
        "model_error": request.app.state.recognizer_error,
    }
