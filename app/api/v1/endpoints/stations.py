from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.models import User
from app.schemas.station import StationListResponse
from app.services.stations import nearby_stations

router = APIRouter()


@router.get("/stations/nearby", response_model=StationListResponse)
def stations_nearby(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(get_current_user),
) -> StationListResponse:
    """Stations around a point, nearest first.

    `distance_m` is straight-line distance; the app displays it directly and
    computes nothing itself.
    """
    return StationListResponse(stations=nearby_stations(lat, lon, limit))
