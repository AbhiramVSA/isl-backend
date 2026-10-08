import logging

from sqlalchemy import update

from app.db import SessionLocal
from app.models import Report
from app.services.google_maps import GoogleMapsClient, LatLng, google_maps
from app.services.realtime import realtime_hub

logger = logging.getLogger(__name__)


async def geocode_report(
    public_id: str, latitude: float, longitude: float, maps: GoogleMapsClient = google_maps
) -> None:
    if not maps.enabled:
        return
    try:
        result = await maps.reverse_geocode(LatLng(latitude, longitude))
    except Exception as exc:
        logger.warning("Reverse geocoding failed for report %s: %s", public_id, exc)
        return
    if not result.formatted_address and not result.plus_code:
        return
    async with SessionLocal() as db:
        office_id = await db.scalar(
            update(Report)
            .where(Report.public_id == public_id)
            .values(
                formatted_address=(result.formatted_address or "")[:500] or None,
                plus_code=result.plus_code,
            )
            .returning(Report.office_id)
        )
        await db.commit()
    if office_id is not None:
        await realtime_hub.office_event(
            office_id, {"type": "report.updated", "report_id": public_id, "address": True}
        )
