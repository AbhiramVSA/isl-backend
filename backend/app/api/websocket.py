from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.security import decode_token
from app.db import SessionLocal
from app.models import (
    Account,
    AccountStatus,
    Office,
    OfficeMembership,
    Officer,
    Report,
    ReportHistory,
    ReportLocation,
    Role,
    User,
)
from app.schemas import LocationCreate, LocationOut
from app.services.realtime import realtime_hub

router = APIRouter(tags=["Real-time updates"])


def websocket_token(websocket: WebSocket) -> str:
    token = websocket.query_params.get("access_token")
    if not token:
        raise ValueError("missing credentials")
    return token


@router.websocket("/ws/officer")
async def officer_socket(websocket: WebSocket) -> None:
    try:
        payload = decode_token(websocket_token(websocket))
        if payload["role"] not in {Role.OFFICER.value, Role.ADMIN.value}:
            raise ValueError("incorrect role")
        async with SessionLocal() as db:
            account = await db.get(Account, int(payload["sub"]))
            if not account or account.status != AccountStatus.ACTIVE:
                raise ValueError("inactive account")
            if payload["role"] == Role.ADMIN.value:
                ids = tuple(
                    (await db.scalars(select(Office.id).where(Office.active.is_(True)))).all()
                )
            else:
                officer = await db.scalar(
                    select(Officer).where(Officer.account_id == int(payload["sub"]))
                )
                if not officer:
                    raise ValueError("missing officer")
                ids = tuple(
                    (
                        await db.scalars(
                            select(OfficeMembership.office_id).where(
                                OfficeMembership.officer_id == officer.id,
                                OfficeMembership.active.is_(True),
                            )
                        )
                    ).all()
                )
        await realtime_hub.connect_officer(ids, websocket)
        await websocket.send_json({"type": "connected"})
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        if websocket.client_state.name == "CONNECTED":
            await websocket.close(code=4401)
    finally:
        await realtime_hub.disconnect(websocket)


@router.websocket("/ws/user")
async def user_socket(websocket: WebSocket) -> None:
    try:
        payload = decode_token(websocket_token(websocket))
        if payload["role"] != Role.USER.value:
            raise ValueError("incorrect role")
        async with SessionLocal() as db:
            account = await db.get(Account, int(payload["sub"]))
            if not account or account.status != AccountStatus.ACTIVE:
                raise ValueError("inactive account")
            user = await db.scalar(select(User).where(User.account_id == int(payload["sub"])))
            if not user:
                raise ValueError("missing user")
        await realtime_hub.connect_user(user.id, websocket)
        await websocket.send_json({"type": "connected"})
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif message.get("type") == "location.update":
                try:
                    location_data = LocationCreate.model_validate(message)
                except ValueError:
                    await websocket.send_json(
                        {"type": "location.rejected", "message": "Location could not be updated."}
                    )
                    continue
                async with SessionLocal() as db:
                    report = await db.scalar(
                        select(Report).where(
                            Report.public_id == message.get("report_id"),
                            Report.user_id == user.id,
                        )
                    )
                    if not report or report.status.value in {"RESOLVED", "CANCELLED"}:
                        await websocket.send_json(
                            {
                                "type": "location.rejected",
                                "message": "This report is no longer active.",
                            }
                        )
                        continue
                    location = ReportLocation(
                        report_id=report.id,
                        **location_data.model_dump(exclude_none=True),
                    )
                    db.add(location)
                    await db.flush()
                    db.add(
                        ReportHistory(
                            report_id=report.id,
                            actor_type="USER",
                            actor_id=user.id,
                            event="LOCATION_UPDATED",
                            new_status=report.status.value,
                            event_metadata={},
                        )
                    )
                    await db.commit()
                    await db.refresh(location)
                await websocket.send_json({"type": "location.accepted"})
                await realtime_hub.office_event(
                    report.office_id,
                    {
                        "type": "location.updated",
                        "report_id": report.public_id,
                        "location": LocationOut.model_validate(location).model_dump(mode="json"),
                    },
                )
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        if websocket.client_state.name == "CONNECTED":
            await websocket.close(code=4401)
    finally:
        await realtime_hub.disconnect(websocket)
