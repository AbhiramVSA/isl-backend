import os

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_incident.db"
os.environ["SECRET_KEY"] = "test-secret-key-with-sufficient-length"

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import Base, SessionLocal, engine
from app.main import app


@pytest.fixture(autouse=True)
async def clean_database():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def db():
    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
