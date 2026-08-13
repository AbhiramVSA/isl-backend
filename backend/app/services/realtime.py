import asyncio
from collections import defaultdict

from fastapi import WebSocket


class RealtimeHub:
    def __init__(self) -> None:
        self._office_connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._user_connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect_officer(self, office_ids: tuple[int, ...], websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            for office_id in office_ids:
                self._office_connections[office_id].add(websocket)

    async def connect_user(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._user_connections[user_id].add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            for connections in (
                *self._office_connections.values(),
                *self._user_connections.values(),
            ):
                connections.discard(websocket)

    async def office_event(self, office_id: int, event: dict) -> None:
        await self._send(self._office_connections.get(office_id, set()), event)

    async def user_event(self, user_id: int, event: dict) -> None:
        await self._send(self._user_connections.get(user_id, set()), event)

    async def _send(self, targets: set[WebSocket], event: dict) -> None:
        stale: list[WebSocket] = []
        for websocket in tuple(targets):
            try:
                await websocket.send_json(event)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(websocket)


realtime_hub = RealtimeHub()
