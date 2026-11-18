from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings

ROUTE_MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
COMPUTE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
NEARBY_SEARCH_URL = "https://places.googleapis.com/v1/places:searchNearby"

MATRIX_FIELDS = "originIndex,destinationIndex,status,condition,duration,distanceMeters"
ROUTE_FIELDS = "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline"
NEARBY_FIELDS = "places.id,places.displayName,places.formattedAddress,places.location"


class GoogleMapsError(Exception):
    pass


@dataclass(frozen=True)
class LatLng:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class MatrixElement:
    origin_index: int
    destination_index: int
    duration_seconds: int
    distance_meters: int


@dataclass(frozen=True)
class RouteSummary:
    duration_seconds: int
    distance_meters: int
    encoded_polyline: str


@dataclass(frozen=True)
class ReverseGeocode:
    formatted_address: str | None
    plus_code: str | None


@dataclass(frozen=True)
class NearbyPlace:
    place_id: str
    name: str
    address: str | None
    latitude: float
    longitude: float


def waypoint(point: LatLng) -> dict[str, Any]:
    return {
        "waypoint": {
            "location": {"latLng": {"latitude": point.latitude, "longitude": point.longitude}}
        }
    }


def seconds(value: str | None) -> int:
    if not value:
        return 0
    return round(float(value.rstrip("s")))


class GoogleMapsClient:
    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 1.5,
        retries: int = 1,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def _request(
        self, method: str, url: str, field_mask: str | None = None, **kwargs: Any
    ) -> Any:
        if not self.enabled:
            raise GoogleMapsError("Google Maps server key is not configured")
        headers = {"X-Goog-Api-Key": self.api_key}
        if field_mask:
            headers["X-Goog-FieldMask"] = field_mask
        failure: str = "no attempt made"
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, transport=self.transport
        ) as client:
            for _ in range(self.retries + 1):
                try:
                    response = await client.request(method, url, headers=headers, **kwargs)
                except httpx.HTTPError as exc:
                    failure = f"{type(exc).__name__}: {exc}"
                    continue
                if response.status_code >= 500:
                    failure = f"HTTP {response.status_code}"
                    continue
                if response.status_code >= 400:
                    raise GoogleMapsError(f"HTTP {response.status_code}: {response.text[:200]}")
                return response.json()
        raise GoogleMapsError(failure)

    async def route_matrix(
        self, origins: list[LatLng], destinations: list[LatLng]
    ) -> list[MatrixElement]:
        body = {
            "origins": [waypoint(point) for point in origins],
            "destinations": [waypoint(point) for point in destinations],
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
        }
        data = await self._request("POST", ROUTE_MATRIX_URL, MATRIX_FIELDS, json=body)
        if not isinstance(data, list):
            raise GoogleMapsError("Unexpected route matrix response")
        return [
            MatrixElement(
                origin_index=item.get("originIndex", 0),
                destination_index=item.get("destinationIndex", 0),
                duration_seconds=seconds(item.get("duration")),
                distance_meters=item.get("distanceMeters", 0),
            )
            for item in data
            if item.get("condition") == "ROUTE_EXISTS" and not item.get("status", {}).get("code")
        ]

    async def compute_route(self, origin: LatLng, destination: LatLng) -> RouteSummary | None:
        body = {
            "origin": waypoint(origin)["waypoint"],
            "destination": waypoint(destination)["waypoint"],
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
        }
        data = await self._request("POST", COMPUTE_ROUTES_URL, ROUTE_FIELDS, json=body)
        routes = data.get("routes") or []
        if not routes:
            return None
        route = routes[0]
        return RouteSummary(
            duration_seconds=seconds(route.get("duration")),
            distance_meters=route.get("distanceMeters", 0),
            encoded_polyline=route.get("polyline", {}).get("encodedPolyline", ""),
        )

    async def reverse_geocode(self, point: LatLng) -> ReverseGeocode:
        data = await self._request(
            "GET",
            GEOCODE_URL,
            params={"latlng": f"{point.latitude},{point.longitude}", "key": self.api_key},
        )
        status = data.get("status")
        if status not in {"OK", "ZERO_RESULTS"}:
            raise GoogleMapsError(f"Geocoding status {status}")
        results = data.get("results") or []
        return ReverseGeocode(
            formatted_address=results[0].get("formatted_address") if results else None,
            plus_code=(data.get("plus_code") or {}).get("global_code"),
        )

    async def nearby_police_stations(
        self, center: LatLng, radius_meters: float, limit: int = 20
    ) -> list[NearbyPlace]:
        body = {
            "includedTypes": ["police"],
            "maxResultCount": limit,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": center.latitude, "longitude": center.longitude},
                    "radius": radius_meters,
                }
            },
        }
        data = await self._request("POST", NEARBY_SEARCH_URL, NEARBY_FIELDS, json=body)
        return [
            NearbyPlace(
                place_id=place["id"],
                name=(place.get("displayName") or {}).get("text") or place["id"],
                address=place.get("formattedAddress"),
                latitude=place["location"]["latitude"],
                longitude=place["location"]["longitude"],
            )
            for place in data.get("places") or []
            if place.get("id") and place.get("location")
        ]


google_maps = GoogleMapsClient(
    settings.google_maps_server_key,
    timeout_seconds=settings.google_maps_timeout_seconds,
    retries=settings.google_maps_retries,
)
