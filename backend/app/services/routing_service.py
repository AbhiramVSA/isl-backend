import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Office


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@dataclass(frozen=True)
class RoutingResult:
    office: Office
    distance_km: float
    matched_service_area: bool


class RoutingService:
    """Portable routing boundary; replace this implementation with PostGIS later."""

    async def route(self, db: AsyncSession, latitude: float, longitude: float) -> RoutingResult:
        offices = list((await db.scalars(select(Office).where(Office.active.is_(True)))).all())
        if not offices:
            raise LookupError("No active office is available")
        ranked = sorted(
            (
                (office, haversine_km(latitude, longitude, office.latitude, office.longitude))
                for office in offices
            ),
            key=lambda item: item[1],
        )
        responsible = [item for item in ranked if item[1] <= item[0].service_radius]
        office, distance = responsible[0] if responsible else ranked[0]
        return RoutingResult(office, distance, bool(responsible))


routing_service = RoutingService()
