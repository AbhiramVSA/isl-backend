import pytest

from app.models import Office
from app.services.routing_service import haversine_km, routing_service


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
