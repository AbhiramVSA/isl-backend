import json

import httpx
import pytest
from conftest import auth
from test_workflow import create_report, make_officers, officer_login, register_and_login

from app.main import rate_windows
from app.services.google_maps import google_maps

ROUTE = {
    "routes": [{"duration": "540s", "distanceMeters": 4200, "polyline": {"encodedPolyline": "x"}}]
}


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    rate_windows.clear()


def use_maps(monkeypatch, route: httpx.Response) -> list[dict]:
    route_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":computeRoutes"):
            route_bodies.append(json.loads(request.content))
            return route
        if request.url.path.endswith(":computeRouteMatrix"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"status": "ZERO_RESULTS"})

    monkeypatch.setattr(google_maps, "api_key", "test-key")
    monkeypatch.setattr(google_maps, "transport", httpx.MockTransport(handler))
    return route_bodies


async def test_route_goes_from_office_to_latest_location(client, db, monkeypatch):
    office, _ = await make_officers(db)
    route_bodies = use_maps(monkeypatch, httpx.Response(200, json=ROUTE))
    token = await register_and_login(client)
    report = await create_report(client, token)
    officer = auth(await officer_login(client))
    url = f"/api/v1/officer/reports/{report['public_id']}/route"

    initial = await client.get(url, headers=officer)
    assert initial.status_code == 200, initial.text
    assert initial.json()["destination_latitude"] == 16.5062
    assert initial.json()["accuracy"] == 7.5

    moved = await client.post(
        f"/api/v1/reports/{report['public_id']}/location",
        headers=auth(token),
        json={"latitude": 16.51, "longitude": 80.66, "accuracy": 40},
    )
    assert moved.status_code == 201

    latest = await client.get(url, headers=officer)
    body = latest.json()
    assert (body["destination_latitude"], body["destination_longitude"]) == (16.51, 80.66)
    assert (body["origin_latitude"], body["origin_longitude"]) == (
        office.latitude,
        office.longitude,
    )
    assert body["accuracy"] == 40
    assert (body["duration_seconds"], body["distance_meters"], body["encoded_polyline"]) == (
        540,
        4200,
        "x",
    )
    destination = route_bodies[-1]["destination"]["location"]["latLng"]
    assert destination == {"latitude": 16.51, "longitude": 80.66}


async def test_route_errors_are_reported_without_breaking_the_report(client, db, monkeypatch):
    await make_officers(db)
    token = await register_and_login(client)
    report = await create_report(client, token)
    officer = auth(await officer_login(client))
    url = f"/api/v1/officer/reports/{report['public_id']}/route"

    assert (await client.get(url, headers=officer)).status_code == 503

    use_maps(monkeypatch, httpx.Response(200, json={}))
    assert (await client.get(url, headers=officer)).status_code == 404

    use_maps(monkeypatch, httpx.Response(500))
    assert (await client.get(url, headers=officer)).status_code == 502

    detail = await client.get(f"/api/v1/officer/reports/{report['public_id']}", headers=officer)
    assert detail.status_code == 200


async def test_reporter_cannot_read_the_route(client, db, monkeypatch):
    await make_officers(db)
    use_maps(monkeypatch, httpx.Response(200, json=ROUTE))
    token = await register_and_login(client)
    report = await create_report(client, token)

    response = await client.get(
        f"/api/v1/officer/reports/{report['public_id']}/route", headers=auth(token)
    )
    assert response.status_code in {401, 403}
