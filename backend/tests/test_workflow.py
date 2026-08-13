from conftest import auth

from app.core.security import hash_password
from app.main import rate_windows
from app.models import Account, Office, OfficeMembership, Officer, Role
from app.services.reports import determine_priority


async def make_officers(db):
    office = Office(
        name="Central Development Office",
        address="Test address",
        latitude=16.506,
        longitude=80.648,
        service_radius=10,
    )
    db.add(office)
    await db.flush()
    records = []
    for index in (1, 2):
        account = Account(
            email=f"officer{index}@test.dev",
            password_hash=hash_password("OfficerPass!234"),
            role=Role.OFFICER,
        )
        db.add(account)
        await db.flush()
        officer = Officer(account_id=account.id, name=f"Officer {index}", badge_number=f"T-{index}")
        db.add(officer)
        await db.flush()
        db.add(OfficeMembership(office_id=office.id, officer_id=officer.id))
        records.append(officer)
    await db.commit()
    return office, records


async def register_and_login(client):
    registration = await client.post(
        "/api/v1/auth/users/register",
        json={
            "email": "reporter@test.dev",
            "phone": "9876543210",
            "password": "ReporterPass!234",
            "name": "Test Reporter",
        },
    )
    assert registration.status_code == 201
    duplicate = await client.post(
        "/api/v1/auth/users/register",
        json={
            "email": "reporter@test.dev",
            "password": "ReporterPass!234",
            "name": "Test Reporter",
        },
    )
    assert duplicate.status_code == 409
    login = await client.post(
        "/api/v1/auth/users/login",
        json={"email": "reporter@test.dev", "password": "ReporterPass!234"},
    )
    assert login.status_code == 200
    return login.json()["access_token"]


async def officer_login(client, number=1):
    response = await client.post(
        "/api/v1/auth/officers/login",
        json={"email": f"officer{number}@test.dev", "password": "OfficerPass!234"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


async def create_report(client, token):
    response = await client.post(
        "/api/v1/reports",
        headers=auth(token),
        json={
            "category": "Road Accident",
            "description": "Two vehicles collided and one person may be injured.",
            "latitude": 16.5062,
            "longitude": 80.6480,
            "location_accuracy": 7.5,
            "answers": {"injuries": True},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_priority_is_rule_driven():
    assert determine_priority("Medical Emergency", {}) == "CRITICAL"
    assert determine_priority("Road Accident", {}) == "HIGH"
    assert determine_priority("Noise complaint", {}) == "NORMAL"


async def test_cors_preflight_does_not_consume_rate_limit(client):
    rate_windows.clear()
    for _ in range(50):
        response = await client.options(
            "/api/v1/officer/reports?page_size=100",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert response.status_code == 200
    assert not rate_windows


async def test_complete_authenticated_workflow(client, db):
    office, _ = await make_officers(db)
    user_token = await register_and_login(client)
    report = await create_report(client, user_token)
    assert report["office"]["id"] == office.id
    assert report["priority"] == "HIGH"
    assert report["status"] == "NEW"

    officer_token = await officer_login(client)
    queue = await client.get("/api/v1/officer/reports", headers=auth(officer_token))
    assert queue.status_code == 200 and queue.json()["total"] == 1
    report_id = report["public_id"]
    reporter = await client.get(
        f"/api/v1/officer/reports/{report_id}/reporter", headers=auth(officer_token)
    )
    assert reporter.status_code == 200
    assert reporter.json()["name"] == "Test Reporter"
    assert reporter.json()["email"] == "reporter@test.dev"
    assert reporter.json()["total_reports"] == 1
    assert "password_hash" not in reporter.text
    for action, expected in (
        ("acknowledge", "ACKNOWLEDGED"),
        ("respond", "RESPONDING"),
        ("arrive", "ARRIVED"),
        ("resolve", "RESOLVED"),
    ):
        response = await client.post(
            f"/api/v1/officer/reports/{report_id}/{action}", headers=auth(officer_token)
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == expected
    invalid = await client.post(
        f"/api/v1/officer/reports/{report_id}/respond", headers=auth(officer_token)
    )
    assert invalid.status_code == 409
    history = await client.get(
        f"/api/v1/officer/reports/{report_id}/history", headers=auth(officer_token)
    )
    assert history.status_code == 200
    assert {item["event"] for item in history.json()} >= {
        "REPORT_CREATED",
        "OFFICE_ASSIGNED",
        "OFFICER_ACKNOWLEDGED",
        "RESOLVED",
    }


async def test_atomic_assignment_conflict_and_resource_authorization(client, db):
    await make_officers(db)
    user_token = await register_and_login(client)
    report = await create_report(client, user_token)
    first, second = await officer_login(client, 1), await officer_login(client, 2)
    accepted = await client.post(
        f"/api/v1/officer/reports/{report['public_id']}/acknowledge", headers=auth(first)
    )
    conflict = await client.post(
        f"/api/v1/officer/reports/{report['public_id']}/acknowledge", headers=auth(second)
    )
    assert accepted.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Another officer has already taken this report"
    forbidden = await client.get(
        f"/api/v1/officer/reports/{report['public_id']}", headers=auth(user_token)
    )
    assert forbidden.status_code == 403


async def test_location_validation_and_live_video_authorization(client, db):
    await make_officers(db)
    token = await register_and_login(client)
    invalid = await client.post(
        "/api/v1/reports",
        headers=auth(token),
        json={
            "category": "Concern",
            "description": "Test report",
            "latitude": 190,
            "longitude": 80,
        },
    )
    assert invalid.status_code == 422
    report = await create_report(client, token)
    location = await client.post(
        f"/api/v1/reports/{report['public_id']}/location",
        headers=auth(token),
        json={"latitude": 16.507, "longitude": 80.649, "accuracy": 5},
    )
    assert location.status_code == 201
    unauthenticated = await client.get(f"/api/v1/reports/{report['public_id']}/stream")
    assert unauthenticated.status_code in {401, 403}
    officer = await officer_login(client)
    request = await client.post(
        f"/api/v1/officer/reports/{report['public_id']}/stream/request", headers=auth(officer)
    )
    assert request.status_code == 200
    assert request.json()["requested"] is True
    started = await client.post(
        f"/api/v1/reports/{report['public_id']}/stream/start", headers=auth(token)
    )
    assert started.status_code == 200
    assert started.json()["active"] is True
    recording = await client.post(
        f"/api/v1/reports/{report['public_id']}/stream/record", headers=auth(token)
    )
    assert recording.status_code == 200
    stopped = await client.post(
        f"/api/v1/reports/{report['public_id']}/stream/stop", headers=auth(token)
    )
    assert stopped.status_code == 200
    assert stopped.json()["active"] is False
    videos = await client.get(
        f"/api/v1/officer/reports/{report['public_id']}/videos", headers=auth(officer)
    )
    assert videos.status_code == 200
    assert videos.json() == []


async def test_refresh_rotation_and_officer_role_boundary(client, db):
    await make_officers(db)
    user_token = await register_and_login(client)
    wrong_portal = await client.post(
        "/api/v1/auth/officers/login",
        json={"email": "reporter@test.dev", "password": "ReporterPass!234"},
    )
    assert wrong_portal.status_code == 401
    login = await client.post(
        "/api/v1/auth/users/login",
        json={"email": "reporter@test.dev", "password": "ReporterPass!234"},
    )
    old_refresh = login.json()["refresh_token"]
    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert rotated.status_code == 200
    reused = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert reused.status_code == 401
    forbidden_queue = await client.get("/api/v1/officer/reports", headers=auth(user_token))
    assert forbidden_queue.status_code == 403
