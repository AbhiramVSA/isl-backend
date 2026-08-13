import os

from fastapi import APIRouter, HTTPException, Request, UploadFile

from app.schemas import PredictionResponse
from app.services.isl import ALLOWED_EXTENSIONS

router = APIRouter()


@router.post("/predict", response_model=PredictionResponse)
def predict(request: Request, file: UploadFile):
    recognizer = request.app.state.recognizer
    if recognizer is None:
        raise HTTPException(
            status_code=503,
            detail=f"Model not loaded: {request.app.state.recognizer_error}",
        )
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video format {suffix!r}; expected one of {sorted(ALLOWED_EXTENSIONS)}",
        )
    try:
        label = recognizer.predict(file.file.read(), suffix)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PredictionResponse(label=label)
