import httpx
import pytest
from conftest import auth
from sqlalchemy import select
from test_mobile_app import BASE, SUBMISSION, make_office, sign_in

from app.main import rate_windows
from app.models import Report
from app.services.geocoding import geocode_report
from app.services.google_maps import GoogleMapsClient, google_maps

GEOCODE = {
    "status": "OK",
    "plus_code": {"global_code": "7J4VFF8G+CQ"},
    "results": [{"formatted_address": "Thullur, Andhra Pradesh 522237, India"}],
}


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    rate_windows.clear()
    yield
    rate_windows.clear()


def geocoder(handler) -> GoogleMapsClient:
    return GoogleMapsClient("test-key", transport=httpx.MockTransport(handler))


def use_geocoder(monkeypatch, handler) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    monkeypatch.setattr(google_maps, "api_key", "test-key")
    monkeypatch.setattr(google_maps, "transport", httpx.MockTransport(recording))
    return requests


async def filed_report(client, db) -> Report:
    await make_office(db)
    token = await sign_in(client)
    response = await client.post(f"{BASE}/reports", json=SUBMISSION, headers=auth(token))
    assert response.status_code == 201, response.text
    return await db.scalar(select(Report))


async def test_geocode_report_stores_address_and_plus_code(client, db):
    report = await filed_report(client, db)

    await geocode_report(
        report.public_id, 16.5261, 80.4694, geocoder(lambda _: httpx.Response(200, json=GEOCODE))
    )

    await db.refresh(report)
    assert report.formatted_address == "Thullur, Andhra Pradesh 522237, India"
    assert report.plus_code == "7J4VFF8G+CQ"


async def test_geocode_failure_leaves_report_untouched(client, db):
    report = await filed_report(client, db)

    def failing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("down", request=request)

    await geocode_report(report.public_id, 16.5261, 80.4694, geocoder(failing))

    await db.refresh(report)
    assert report.formatted_address is None
    assert report.plus_code is None


async def test_app_report_is_geocoded_after_it_is_saved(client, db, monkeypatch):
    await make_office(db)
    token = await sign_in(client)
    requests = use_geocoder(monkeypatch, lambda _: httpx.Response(200, json=GEOCODE))

    response = await client.post(f"{BASE}/reports", json=SUBMISSION, headers=auth(token))

    assert response.status_code == 201, response.text
    report = await db.scalar(select(Report))
    assert report.formatted_address == "Thullur, Andhra Pradesh 522237, India"
    assert report.plus_code == "7J4VFF8G+CQ"
    geocodes = [r for r in requests if r.url.host == "maps.googleapis.com"]
    assert [r.url.params["latlng"] for r in geocodes] == ["16.5261,80.4694"]


async def test_report_without_location_is_not_geocoded(client, db, monkeypatch):
    await make_office(db)
    token = await sign_in(client)
    requests = use_geocoder(monkeypatch, lambda _: httpx.Response(200, json=GEOCODE))
    submission = {**SUBMISSION, "latitude": None, "longitude": None}

    response = await client.post(f"{BASE}/reports", json=submission, headers=auth(token))

    assert response.status_code == 201, response.text
    assert [r for r in requests if r.url.host == "maps.googleapis.com"] == []
    assert (await db.scalar(select(Report))).formatted_address is None


async def test_geocoding_outage_does_not_block_report_creation(client, db, monkeypatch):
    office = await make_office(db)
    token = await sign_in(client)
    use_geocoder(monkeypatch, lambda _: httpx.Response(503))

    response = await client.post(f"{BASE}/reports", json=SUBMISSION, headers=auth(token))

    assert response.status_code == 201, response.text
    report = await db.scalar(select(Report))
    assert report.office_id == office.id
    assert report.route_source == "haversine"
    assert report.formatted_address is None
