from fastapi import APIRouter, HTTPException, Request, UploadFile

from app.schemas import PredictionResponse

router = APIRouter()


@router.post("/predict", response_model=PredictionResponse)
async def predict(request: Request, file: UploadFile):
    recognizer = request.app.state.recognizer
    if recognizer is None:
        raise HTTPException(
            status_code=503,
            detail=f"Model not loaded: {request.app.state.recognizer_error}",
        )
    try:
        label = recognizer.predict(await file.read())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PredictionResponse(label=label)
