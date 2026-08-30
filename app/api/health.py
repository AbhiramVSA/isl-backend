from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request):
    try:
        import tensorflow as tf

        gpus = [gpu.name for gpu in tf.config.list_physical_devices("GPU")]
    except Exception:
        gpus = []
    return {
        "status": "ok",
        "model_loaded": request.app.state.recognizer is not None,
        "model_error": request.app.state.recognizer_error,
        "gpus": gpus,
    }
