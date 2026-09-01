"""The Equal mobile app's API.

The risk these cover is not a missing field — the app would show that on first
run. It is the two dialects drifting: a status the app cannot read, a severity
that loses its meaning on the way in, a retry that files a second incident, or
one of these routes quietly shadowing the console's.
"""

from conftest import auth
from sqlalchemy import select

from app.models import Office, Report, ReportStatus

BASE = "/app/api/v1"

SUBMISSION = {
    "client_id": "01J8ZC4K7M2N3P4Q5R6S7T8U9V",
    "created_at": "2026-08-14T02:59:11Z",
    "title": "Medical emergency reported in Indian Sign Language",
    "category": "MedicalEmergency",
    "severity": "Critical",
    "summary": "A caller signed that someone has collapsed and is not responding.",
    "situation_analysis": "SITUATION\nSomeone is hurt.\n\nACCESSIBILITY\nThe caller is Deaf.",
    "recommended_actions": ["Dispatch an ambulance.", "Contact in writing only."],
    "transcript": "Hello",
    "labels": ["Hello"],
    "duration_ms": 5000,
    "latitude": 16.5261,
    "longitude": 80.4694,
    "location_label": "Thullur, Guntur District",
    "reporter_name": "Anitha D.",
    "source": "sign_video",
    "generated_by": "meta/muse-glimmer-30b",
}


async def make_office(db) -> Office:
    office = Office(
        name="Thullur Police Station",
        address="Thullur, Guntur District",
        latitude=16.5261,
        longitude=80.4694,
        service_radius=15,
    )
    db.add(office)
    await db.commit()
    return office


async def sign_in(client, identifier="+919876543210", passcode="secret") -> str:
    response = await client.post(
        f"{BASE}/auth/login", json={"identifier": identifier, "passcode": passcode}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def test_login_creates_the_account_on_first_use(client):
    response = await client.post(
        f"{BASE}/auth/login", json={"identifier": "priya.n@mail.com", "passcode": "hunter2"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["display_name"] == "Priya N"
    assert body["user"]["identifier"] == "priya.n@mail.com"
    assert body["user"]["preferred_language"] == "Indian Sign Language"
    assert body["access_token"] and body["expires_at"]


async def test_second_login_requires_the_same_passcode(client):
    await client.post(f"{BASE}/auth/login", json={"identifier": "a@b.co", "passcode": "hunter2"})

    wrong = await client.post(
        f"{BASE}/auth/login", json={"identifier": "a@b.co", "passcode": "not-it"}
    )
    right = await client.post(
        f"{BASE}/auth/login", json={"identifier": "a@b.co", "passcode": "hunter2"}
    )

    assert wrong.status_code == 401
    assert right.status_code == 200


async def test_a_stored_token_can_be_checked(client):
    token = await sign_in(client)

    response = await client.get(f"{BASE}/auth/me", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["id"].startswith("usr_")


async def test_health_reports_whether_signing_will_work(client):
    """The app reads model_loaded before it lets anyone record. The console's
    own /health answers {"status": "ok"} and would fail the app's parser."""
    response = await client.get("/app/health")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "model_loaded", "model_error"}
    assert isinstance(body["model_loaded"], bool)


async def test_submitting_stores_the_whole_document(client, db):
    await make_office(db)
    token = await sign_in(client)

    response = await client.post(f"{BASE}/reports", json=SUBMISSION, headers=auth(token))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"].startswith("rpt_")
    assert body["reference_code"].startswith("SOS-")
    assert body["status"] == "Submitted"
    # The parts a summary alone would have thrown away.
    assert body["situation_analysis"] == SUBMISSION["situation_analysis"]
    assert body["recommended_actions"] == SUBMISSION["recommended_actions"]
    assert body["transcript"] == "Hello"
    assert body["severity"] == "Critical"


async def test_the_report_lands_in_the_console_queue(client, db):
    """One table, two dialects: what the app files is what an officer opens."""
    office = await make_office(db)
    token = await sign_in(client)

    await client.post(f"{BASE}/reports", json=SUBMISSION, headers=auth(token))

    report = await db.scalar(select(Report))
    assert report.office_id == office.id
    assert report.status is ReportStatus.NEW
    # Critical severity has to arrive as a priority the console sorts on.
    assert report.priority.value == "CRITICAL"
    assert report.description == SUBMISSION["summary"]


async def test_a_retry_does_not_file_twice(client, db):
    """A caller retrying over a bad connection must not create two incidents."""
    await make_office(db)
    token = await sign_in(client)

    first = await client.post(f"{BASE}/reports", json=SUBMISSION, headers=auth(token))
    second = await client.post(f"{BASE}/reports", json=SUBMISSION, headers=auth(token))

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    listing = await client.get(f"{BASE}/reports", headers=auth(token))
    assert len(listing.json()["reports"]) == 1


async def test_the_client_cannot_choose_its_own_status_or_code(client, db):
    await make_office(db)
    token = await sign_in(client)

    response = await client.post(
        f"{BASE}/reports",
        json={**SUBMISSION, "status": "Resolved", "reference_code": "SOS-HACKED"},
        headers=auth(token),
    )

    assert response.status_code == 201
    assert response.json()["status"] == "Submitted"
    assert response.json()["reference_code"] != "SOS-HACKED"


async def test_unknown_enums_are_rejected(client, db):
    await make_office(db)
    token = await sign_in(client)

    category = await client.post(
        f"{BASE}/reports", json={**SUBMISSION, "category": "Alien Invasion"}, headers=auth(token)
    )
    severity = await client.post(
        f"{BASE}/reports", json={**SUBMISSION, "severity": "Spicy"}, headers=auth(token)
    )

    assert category.status_code == 422
    assert severity.status_code == 422


async def test_a_report_without_a_location_still_routes(client, db):
    """Declining to share a position must not mean reaching nobody."""
    await make_office(db)
    token = await sign_in(client)

    response = await client.post(
        f"{BASE}/reports",
        json={**SUBMISSION, "latitude": None, "longitude": None, "client_id": "no-location"},
        headers=auth(token),
    )

    assert response.status_code == 201, response.text
    report = await db.scalar(select(Report))
    assert report.office_id is not None


async def test_officer_progress_reaches_the_caller_in_their_own_words(client, db):
    """The console's seven statuses folded onto the five the app understands.
    Sending RESPONDING raw would degrade to "Submitted" on the device, which
    reads as the report going backwards."""
    await make_office(db)
    token = await sign_in(client)
    filed = (await client.post(f"{BASE}/reports", json=SUBMISSION, headers=auth(token))).json()

    report = await db.scalar(select(Report))
    report.status = ReportStatus.RESPONDING
    await db.commit()

    response = await client.get(f"{BASE}/reports/{filed['reference_code']}", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["status"] == "UnitDispatched"


async def test_another_caller_cannot_read_the_report(client, db):
    await make_office(db)
    mine = await sign_in(client)
    filed = (await client.post(f"{BASE}/reports", json=SUBMISSION, headers=auth(mine))).json()

    theirs = await sign_in(client, identifier="+919000000000")
    response = await client.get(f"{BASE}/reports/{filed['id']}", headers=auth(theirs))

    # The same answer as a report that does not exist, so this cannot be used to
    # find out which ids are real.
    assert response.status_code == 404


async def test_nearby_stations_are_the_offices_reports_route_to(client, db):
    await make_office(db)
    token = await sign_in(client)

    response = await client.get(f"{BASE}/stations/nearby?lat=16.52&lon=80.47", headers=auth(token))

    assert response.status_code == 200
    stations = response.json()["stations"]
    assert stations[0]["name"] == "Thullur Police Station"
    assert stations[0]["distance_m"] >= 0
    # No office carries a phone number, and a wrong one on an emergency screen is
    # worse than none.
    assert stations[0]["phone"] == ""
    assert stations[0]["sign_language_officer"] is False


async def test_the_llm_proxy_says_so_when_it_has_no_key(client):
    token = await sign_in(client)

    response = await client.post(f"{BASE}/llm/chat", json={"messages": []}, headers=auth(token))

    assert response.status_code == 503


async def test_the_consoles_own_routes_are_untouched(client):
    """These live at /api/v1; the app's at /app/api/v1. If the mount ever
    started shadowing, this is what would catch it."""
    console = await client.post("/api/v1/reports", json={})
    assert console.status_code == 401  # authentication, not a 404 or a 422

    console_health = await client.get("/health")
    assert console_health.json() == {"status": "ok"}
