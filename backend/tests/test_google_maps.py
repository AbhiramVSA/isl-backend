import json

import httpx
import pytest

from app.services.google_maps import GoogleMapsClient, GoogleMapsError, LatLng


def client_with(handler) -> GoogleMapsClient:
    return GoogleMapsClient("test-key", transport=httpx.MockTransport(handler))


async def test_disabled_client_refuses_to_call():
    client = GoogleMapsClient("")
    assert client.enabled is False
    with pytest.raises(GoogleMapsError):
        await client.reverse_geocode(LatLng(16.5, 80.6))


async def test_route_matrix_sends_field_mask_and_skips_missing_routes():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["mask"] = request.headers["X-Goog-FieldMask"]
        seen["key"] = request.headers["X-Goog-Api-Key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=[
                {
                    "originIndex": 0,
                    "destinationIndex": 0,
                    "duration": "420s",
                    "distanceMeters": 3100,
                    "condition": "ROUTE_EXISTS",
                },
                {"originIndex": 1, "destinationIndex": 0, "condition": "ROUTE_NOT_FOUND"},
                {
                    "originIndex": 2,
                    "destinationIndex": 0,
                    "status": {"code": 3},
                    "condition": "ROUTE_EXISTS",
                },
            ],
        )

    elements = await client_with(handler).route_matrix(
        [LatLng(16.5, 80.6), LatLng(16.6, 80.7), LatLng(16.7, 80.8)], [LatLng(16.51, 80.61)]
    )
    assert seen["key"] == "test-key"
    assert "duration" in seen["mask"] and "distanceMeters" in seen["mask"]
    assert seen["body"]["routingPreference"] == "TRAFFIC_AWARE"
    assert len(seen["body"]["origins"]) == 3
    assert [(e.origin_index, e.duration_seconds, e.distance_meters) for e in elements] == [
        (0, 420, 3100)
    ]


async def test_retries_once_then_raises_on_timeout():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(GoogleMapsError):
        await client_with(handler).route_matrix([LatLng(16.5, 80.6)], [LatLng(16.51, 80.61)])
    assert calls == 2


async def test_server_error_is_retried_and_can_recover():
    responses = [httpx.Response(503), httpx.Response(200, json=[])]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    assert await client_with(handler).route_matrix([LatLng(1, 1)], [LatLng(2, 2)]) == []
    assert responses == []


async def test_client_error_is_not_retried():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, text="denied")

    with pytest.raises(GoogleMapsError):
        await client_with(handler).route_matrix([LatLng(1, 1)], [LatLng(2, 2)])
    assert calls == 1


async def test_reverse_geocode_returns_address_and_plus_code():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["latlng"] == "16.5062,80.648"
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "plus_code": {"global_code": "7J4VGJ4X+FV"},
                "results": [{"formatted_address": "MG Road, Vijayawada, Andhra Pradesh"}],
            },
        )

    result = await client_with(handler).reverse_geocode(LatLng(16.5062, 80.648))
    assert result.formatted_address == "MG Road, Vijayawada, Andhra Pradesh"
    assert result.plus_code == "7J4VGJ4X+FV"


async def test_reverse_geocode_zero_results_keeps_plus_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "ZERO_RESULTS", "plus_code": {"global_code": "7J4V0000+00"}}
        )

    result = await client_with(handler).reverse_geocode(LatLng(16.5, 80.6))
    assert result.formatted_address is None
    assert result.plus_code == "7J4V0000+00"


async def test_reverse_geocode_denied_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "REQUEST_DENIED"})

    with pytest.raises(GoogleMapsError):
        await client_with(handler).reverse_geocode(LatLng(16.5, 80.6))


async def test_compute_route_returns_polyline():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "routes": [
                    {
                        "duration": "615s",
                        "distanceMeters": 5400,
                        "polyline": {"encodedPolyline": "abc"},
                    }
                ]
            },
        )

    route = await client_with(handler).compute_route(LatLng(16.5, 80.6), LatLng(16.51, 80.61))
    assert route is not None
    assert (route.duration_seconds, route.distance_meters, route.encoded_polyline) == (
        615,
        5400,
        "abc",
    )


async def test_compute_route_without_routes_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    assert await client_with(handler).compute_route(LatLng(1, 1), LatLng(2, 2)) is None


async def test_nearby_police_stations_parses_places():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "place-1",
                        "displayName": {"text": "Governorpet Police Station"},
                        "formattedAddress": "Governorpet, Vijayawada",
                        "location": {"latitude": 16.51, "longitude": 80.62},
                    },
                    {"id": "place-2"},
                ]
            },
        )

    places = await client_with(handler).nearby_police_stations(LatLng(16.5, 80.6), 5000)
    assert seen["body"]["includedTypes"] == ["police"]
    assert seen["body"]["locationRestriction"]["circle"]["radius"] == 5000
    assert len(places) == 1
    assert places[0].place_id == "place-1"
    assert places[0].name == "Governorpet Police Station"
