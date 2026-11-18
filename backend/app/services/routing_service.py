import logging
import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Office
from app.services.google_maps import GoogleMapsClient, LatLng, google_maps

logger = logging.getLogger(__name__)

ROUTES_API = "routes_api"
HAVERSINE = "haversine"


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
    eta_seconds: int | None = None
    route_source: str = HAVERSINE
    haversine_office_id: int | None = None


class RoutingService:
    """Portable routing boundary; replace this implementation with PostGIS later."""

    def __init__(self, maps: GoogleMapsClient = google_maps, shortlist_size: int = 5) -> None:
        self.maps = maps
        self.shortlist_size = shortlist_size

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
        nearest = RoutingResult(office, distance, bool(responsible), haversine_office_id=office.id)
        if not self.maps.enabled:
            return nearest
        shortlist = ranked[: self.shortlist_size]
        if (office, distance) not in shortlist:
            shortlist.append((office, distance))
        try:
            fastest = await self._fastest(shortlist, latitude, longitude, nearest)
        except Exception as exc:
            logger.warning("Route matrix failed, using Haversine routing: %s", exc)
            return nearest
        if fastest is None:
            logger.warning("Route matrix returned no routes, using Haversine routing")
            return nearest
        if fastest.office.id != nearest.office.id:
            logger.info(
                "Travel time chose office %s over nearest office %s",
                fastest.office.id,
                nearest.office.id,
            )
        return fastest

    async def _fastest(
        self,
        shortlist: list[tuple[Office, float]],
        latitude: float,
        longitude: float,
        nearest: RoutingResult,
    ) -> RoutingResult | None:
        elements = await self.maps.route_matrix(
            [LatLng(office.latitude, office.longitude) for office, _ in shortlist],
            [LatLng(latitude, longitude)],
        )
        timed = [
            (shortlist[element.origin_index], element.duration_seconds)
            for element in elements
            if 0 <= element.origin_index < len(shortlist)
        ]
        if not timed:
            return None
        in_area = [item for item in timed if item[0][1] <= item[0][0].service_radius]
        (office, distance), eta = min(in_area or timed, key=lambda item: item[1])
        return RoutingResult(
            office,
            distance,
            bool(in_area),
            eta_seconds=eta,
            route_source=ROUTES_API,
            haversine_office_id=nearest.office.id,
        )


routing_service = RoutingService(shortlist_size=settings.routing_shortlist_size)
