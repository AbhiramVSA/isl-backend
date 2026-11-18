import httpx
import pytest
from conftest import auth
from test_roles import login, roster

from app.main import rate_windows
from app.services.google_maps import google_maps

URL = "/api/v1/admin/offices/nearby-stations"
PARAMS = {"latitude": 16.506, "longitude": 80.648, "radius_km": 3}
PLACES = {
    "places": [
        {
            "id": "place-far",
            "displayName": {"text": "Patamata Police Station"},
            "formattedAddress": "Patamata, Vijayawada",
            "location": {"latitude": 16.49, "longitude": 80.67},
        },
        {
            "id": "place-near",
            "displayName": {"text": "Governorpet Police Station"},
            "formattedAddress": "Governorpet, Vijayawada",
            "location": {"latitude": 16.51, "longitude": 80.65},
        },
    ]
}


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    rate_windows.clear()


def use_places(monkeypatch, response: httpx.Response) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response

    monkeypatch.setattr(google_maps, "api_key", "test-key")
    monkeypatch.setattr(google_maps, "transport", httpx.MockTransport(handler))
    return requests


async def test_nearby_stations_are_sorted_and_flag_existing_offices(client, db, monkeypatch):
    central, _, _ = await roster(db)
    central.google_place_id = "place-near"
    await db.commit()
    requests = use_places(monkeypatch, httpx.Response(200, json=PLACES))
    admin = auth(await login(client, "admin"))

    response = await client.get(URL, params=PARAMS, headers=admin)

    assert response.status_code == 200, response.text
    stations = response.json()
    assert [s["place_id"] for s in stations] == ["place-near", "place-far"]
    assert stations[0]["office_id"] == central.id
    assert stations[1]["office_id"] is None
    assert stations[0]["distance_km"] < stations[1]["distance_km"]
    assert requests[0].url.host == "places.googleapis.com"


async def test_only_office_managers_can_search(client, db, monkeypatch):
    await roster(db)
    requests = use_places(monkeypatch, httpx.Response(200, json=PLACES))
    office_admin = auth(await login(client, "office_admin"))

    response = await client.get(URL, params=PARAMS, headers=office_admin)

    assert response.status_code == 403
    assert requests == []


async def test_search_reports_missing_key_and_upstream_errors(client, db, monkeypatch):
    await roster(db)
    admin = auth(await login(client, "admin"))
    assert (await client.get(URL, params=PARAMS, headers=admin)).status_code == 503

    use_places(monkeypatch, httpx.Response(403, text="denied"))
    assert (await client.get(URL, params=PARAMS, headers=admin)).status_code == 502


async def test_station_can_be_added_once_with_its_place_id(client, db):
    await roster(db)
    admin = auth(await login(client, "admin"))
    body = {
        "name": "Governorpet Police Station",
        "address": "Governorpet, Vijayawada",
        "latitude": 16.51,
        "longitude": 80.65,
        "service_radius": 4,
        "google_place_id": "place-near",
    }

    created = await client.post("/api/v1/admin/offices", headers=admin, json=body)
    assert created.status_code == 201, created.text
    assert created.json()["google_place_id"] == "place-near"

    again = await client.post(
        "/api/v1/admin/offices", headers=admin, json={**body, "name": "Duplicate"}
    )
    assert again.status_code == 409
