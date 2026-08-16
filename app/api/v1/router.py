from fastapi import APIRouter

from app.api.v1.endpoints import auth, llm, predict, reports, stations

api_router = APIRouter()
api_router.include_router(predict.router, tags=["prediction"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(reports.router, tags=["reports"])
api_router.include_router(stations.router, tags=["stations"])
api_router.include_router(llm.router, tags=["llm"])
