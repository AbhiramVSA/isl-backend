"""Police station lookup.

Backed by a JSON file so the placeholder directory in `data/` can be swapped for
the real Andhra Pradesh Police one without touching code — point `STATIONS_FILE`
at it, or overwrite the file in place.
"""

import json
import math
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.schemas.station import PoliceStationResponse

EARTH_RADIUS_M = 6_371_000


@lru_cache(maxsize=1)
def _load_stations() -> list[dict]:
    path = Path(settings.stations_file)
    if not path.is_absolute():
        # Resolve relative to the project root, not the working directory, so
        # `uvicorn` started from anywhere still finds the file.
        path = Path(__file__).resolve().parents[2] / path
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("stations", [])


def reload_stations() -> None:
    """Drops the cache. Call after replacing the directory on disk."""
    _load_stations.cache_clear()


def distance_meters(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> int:
    """Great-circle distance. Straight-line, not road distance — see README."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return round(2 * EARTH_RADIUS_M * math.asin(math.sqrt(a)))


def nearby_stations(
    latitude: float, longitude: float, limit: int | None = None
) -> list[PoliceStationResponse]:
    stations = [
        PoliceStationResponse(
            id=station["id"],
            name=station["name"],
            address=station["address"],
            latitude=station["latitude"],
            longitude=station["longitude"],
            distance_m=distance_meters(
                latitude, longitude, station["latitude"], station["longitude"]
            ),
            phone=station.get("phone", ""),
            open_now=station.get("open_now", True),
            sign_language_officer=station.get("sign_language_officer", False),
        )
        for station in _load_stations()
    ]
    stations.sort(key=lambda station: station.distance_m)
    return stations[:limit] if limit else stations
