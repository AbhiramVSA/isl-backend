import os
import tempfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "test-secret")

from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """A client backed by a throwaway SQLite file.

    A file rather than :memory: so the connection pool and the app share the
    same database.
    """
    with tempfile.TemporaryDirectory() as directory:
        engine = create_engine(
            f"sqlite:///{directory}/test.db",
            connect_args={"check_same_thread": False},
        )
        TestingSession = sessionmaker(bind=engine, autoflush=False)
        Base.metadata.create_all(bind=engine)

        def override_get_db() -> Iterator:
            db = TestingSession()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as test_client:
            yield test_client
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.fixture()
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "+919876543210", "passcode": "secret"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def submission() -> dict:
    return {
        "client_id": "01J8ZC4K7M2N3P4Q5R6S7T8U9V",
        "created_at": "2026-08-14T02:59:11Z",
        "title": "Medical emergency reported in Indian Sign Language",
        "category": "MedicalEmergency",
        "severity": "Critical",
        "summary": "A caller reported an injury.",
        "situation_analysis": "SITUATION\nSomeone is hurt.\n\nACCESSIBILITY\nCaller is Deaf.",
        "recommended_actions": ["Dispatch an ambulance.", "Contact in writing only."],
        "transcript": "Hello",
        "labels": ["Hello"],
        "duration_ms": 5000,
        "latitude": 16.5261,
        "longitude": 80.4694,
        "location_label": "Sakhamaru, Andhra Pradesh",
        "reporter_name": "Udhay",
        "source": "sign_video",
        "generated_by": "z-ai/glm-5.2",
    }
