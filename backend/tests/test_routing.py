import json

import httpx
import pytest
from sqlalchemy import select

from app.models import Account, Office, ReportHistory, Role, User
from app.schemas import ReportCreate
from app.services import reports
from app.services.google_maps import GoogleMapsClient
from app.services.routing_service import RoutingService, haversine_km, routing_service


def test_haversine_known_distance():
    distance = haversine_km(16.5062, 80.6480, 16.5150, 80.6300)
    assert distance == pytest.approx(2.15, abs=0.15)


@pytest.mark.asyncio
async def test_routes_inside_service_area_then_nearest_fallback(db):
    near = Office(
        name="Near", address="Development", latitude=16.50, longitude=80.65, service_radius=2
    )
    far = Office(name="Far", address="Development", latitude=17.0, longitude=81.0, service_radius=2)
    db.add_all([near, far])
    await db.commit()
    inside = await routing_service.route(db, 16.501, 80.651)
    assert inside.office.name == "Near"
    assert inside.matched_service_area is True
    fallback = await routing_service.route(db, 16.75, 80.80)
    assert fallback.office.name == "Near"
    assert fallback.matched_service_area is False


def matrix_client(handler) -> GoogleMapsClient:
    return GoogleMapsClient("test-key", transport=httpx.MockTransport(handler))


def element(origin: int, seconds: int) -> dict:
    return {
        "originIndex": origin,
        "destinationIndex": 0,
        "duration": f"{seconds}s",
        "distanceMeters": seconds * 10,
        "condition": "ROUTE_EXISTS",
    }


async def add_river_offices(db) -> tuple[Office, Office]:
    near = Office(
        name="Across river", address="A", latitude=16.500, longitude=80.640, service_radius=10
    )
    slower = Office(
        name="Same bank", address="B", latitude=16.520, longitude=80.660, service_radius=10
    )
    db.add_all([near, slower])
    await db.commit()
    return near, slower


async def test_matrix_picks_faster_office_over_nearer_one(db):
    near, faster = await add_river_offices(db)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["origins"] = len(json.loads(request.content)["origins"])
        return httpx.Response(200, json=[element(0, 1500), element(1, 400)])

    service = RoutingService(matrix_client(handler))
    result = await service.route(db, 16.505, 80.642)
    assert seen["origins"] == 2
    assert result.office.id == faster.id
    assert result.route_source == "routes_api"
    assert result.eta_seconds == 400
    assert result.matched_service_area is True
    assert result.haversine_office_id == near.id


async def test_shortlist_caps_matrix_origins(db):
    db.add_all(
        [
            Office(
                name=f"Office {index}",
                address="X",
                latitude=16.5 + index * 0.01,
                longitude=80.64,
                service_radius=50,
            )
            for index in range(8)
        ]
    )
    await db.commit()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["origins"] = len(json.loads(request.content)["origins"])
        return httpx.Response(200, json=[element(0, 300)])

    result = await RoutingService(matrix_client(handler), shortlist_size=5).route(db, 16.5, 80.64)
    assert seen["origins"] == 5
    assert result.office.name == "Office 0"


async def test_in_area_office_preferred_over_faster_out_of_area_one(db):
    in_area = Office(name="In area", address="A", latitude=16.50, longitude=80.64, service_radius=3)
    outside = Office(name="Outside", address="B", latitude=16.55, longitude=80.64, service_radius=1)
    db.add_all([in_area, outside])
    await db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[element(0, 900), element(1, 200)])

    result = await RoutingService(matrix_client(handler)).route(db, 16.505, 80.64)
    assert result.office.id == in_area.id
    assert result.eta_seconds == 900


@pytest.mark.parametrize(
    "response",
    [
        httpx.ReadTimeout("slow"),
        httpx.Response(500),
        httpx.Response(403, text="quota"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json=[{"originIndex": 0, "condition": "ROUTE_NOT_FOUND"}]),
    ],
    ids=["timeout", "server-error", "api-error", "empty-matrix", "no-route"],
)
async def test_matrix_failures_fall_back_to_haversine(db, response):
    near, _ = await add_river_offices(db)

    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    result = await RoutingService(matrix_client(handler)).route(db, 16.505, 80.642)
    assert result.office.id == near.id
    assert result.route_source == "haversine"
    assert result.eta_seconds is None


async def test_disabled_client_never_calls_out(db):
    near, _ = await add_river_offices(db)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    service = RoutingService(GoogleMapsClient("", transport=httpx.MockTransport(handler)))
    result = await service.route(db, 16.505, 80.642)
    assert result.office.id == near.id
    assert result.route_source == "haversine"


async def test_create_report_records_eta_and_shadow_choice(db, monkeypatch):
    near, faster = await add_river_offices(db)
    account = Account(email="reporter@test.dev", password_hash="x", role=Role.USER)
    db.add(account)
    await db.flush()
    user = User(account_id=account.id, name="Reporter")
    db.add(user)
    await db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[element(0, 1500), element(1, 400)])

    monkeypatch.setattr(reports, "routing_service", RoutingService(matrix_client(handler)))
    report = await reports.create_report(
        db,
        user.id,
        ReportCreate(
            category="Theft", description="Bag snatched", latitude=16.505, longitude=80.642
        ),
    )
    assert report.office_id == faster.id
    assert report.eta_seconds == 400
    assert report.route_source == "routes_api"
    assigned = await db.scalar(
        select(ReportHistory).where(
            ReportHistory.report_id == report.id, ReportHistory.event == "OFFICE_ASSIGNED"
        )
    )
    assert assigned.event_metadata["haversine_office_id"] == near.id
    assert assigned.event_metadata["route_source"] == "routes_api"
