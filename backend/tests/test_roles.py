import pytest
from conftest import auth
from test_workflow import create_report, register_and_login

from app.core.security import hash_password
from app.main import rate_windows
from app.models import Account, Office, OfficeMembership, Officer, Role

PASSWORD = "StaffPass!2345"


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    rate_windows.clear()


async def roster(db):
    """Two offices; staff of every role. The reporter's location routes to `central`."""
    central = Office(
        name="Central", address="A", latitude=16.506, longitude=80.648, service_radius=10
    )
    north = Office(name="North", address="B", latitude=17.5, longitude=80.0, service_radius=5)
    db.add_all([central, north])
    await db.flush()
    people = {}
    for key, role, office in (
        ("admin", Role.ADMIN, None),
        ("auditor", Role.AUDITOR, None),
        ("office_admin", Role.OFFICE_ADMIN, central),
        ("dispatcher", Role.DISPATCHER, central),
        ("officer", Role.OFFICER, central),
        ("north_officer", Role.OFFICER, north),
    ):
        account = Account(email=f"{key}@test.dev", password_hash=hash_password(PASSWORD), role=role)
        db.add(account)
        await db.flush()
        officer = Officer(account_id=account.id, name=key, badge_number=f"B-{key}")
        db.add(officer)
        await db.flush()
        if office:
            db.add(OfficeMembership(office_id=office.id, officer_id=officer.id))
        people[key] = officer
    await db.commit()
    return central, north, people


async def login(client, key):
    response = await client.post(
        "/api/v1/auth/officers/login", json={"email": f"{key}@test.dev", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def test_every_staff_role_signs_in_and_me_lists_permissions(client, db):
    await roster(db)
    for key, label in (
        ("admin", "Super Admin"),
        ("auditor", "Auditor"),
        ("office_admin", "Office Admin"),
        ("dispatcher", "Dispatcher"),
        ("officer", "Officer"),
    ):
        me = (await client.get("/api/v1/auth/me", headers=auth(await login(client, key)))).json()
        assert me["role_label"] == label
    officer_me = (
        await client.get("/api/v1/auth/me", headers=auth(await login(client, "officer")))
    ).json()
    assert "staff.manage" not in officer_me["permissions"]
    assert officer_me["offices"] == ["Central"]


async def test_management_endpoints_follow_permissions(client, db):
    await roster(db)
    officer = auth(await login(client, "officer"))
    dispatcher = auth(await login(client, "dispatcher"))
    auditor = auth(await login(client, "auditor"))
    assert (await client.get("/api/v1/admin/staff", headers=officer)).status_code == 403
    assert (await client.get("/api/v1/admin/audit", headers=dispatcher)).status_code == 403
    assert (await client.get("/api/v1/admin/staff", headers=dispatcher)).status_code == 200
    assert (await client.get("/api/v1/admin/audit", headers=auditor)).status_code == 200
    new = {
        "email": "x@test.dev",
        "password": PASSWORD,
        "name": "New",
        "role": "OFFICER",
        "office_ids": [],
    }
    assert (await client.post("/api/v1/admin/staff", headers=auditor, json=new)).status_code == 403


async def test_office_admin_is_confined_to_their_offices(client, db):
    central, north, people = await roster(db)
    headers = auth(await login(client, "office_admin"))
    base = {"password": PASSWORD, "name": "Recruit"}

    created = await client.post(
        "/api/v1/admin/staff",
        headers=headers,
        json=base | {"email": "r1@test.dev", "role": "OFFICER", "office_ids": [central.id]},
    )
    assert created.status_code == 201, created.text
    assert created.json()["badge_number"].startswith("EQ-")

    other_office = await client.post(
        "/api/v1/admin/staff",
        headers=headers,
        json=base | {"email": "r2@test.dev", "role": "OFFICER", "office_ids": [north.id]},
    )
    assert other_office.status_code == 403
    admin_role = await client.post(
        "/api/v1/admin/staff",
        headers=headers,
        json=base | {"email": "r3@test.dev", "role": "ADMIN", "office_ids": [central.id]},
    )
    assert admin_role.status_code == 403

    listing = (await client.get("/api/v1/admin/staff", headers=headers)).json()
    names = {item["name"] for item in listing["items"]}
    assert "north_officer" not in names and "officer" in names

    foreign = await client.patch(
        f"/api/v1/admin/staff/{people['north_officer'].id}", headers=headers, json={"name": "Xavier"}
    )
    assert foreign.status_code == 403
    promote = await client.patch(
        f"/api/v1/admin/staff/{people['officer'].id}",
        headers=headers,
        json={"role": "OFFICE_ADMIN"},
    )
    assert promote.status_code == 403


async def test_role_change_and_disable_end_existing_sessions(client, db):
    _, _, people = await roster(db)
    admin = auth(await login(client, "admin"))
    officer = auth(await login(client, "officer"))
    assert (await client.get("/api/v1/auth/me", headers=officer)).status_code == 200

    changed = await client.patch(
        f"/api/v1/admin/staff/{people['officer'].id}", headers=admin, json={"role": "DISPATCHER"}
    )
    assert changed.status_code == 200 and changed.json()["role_label"] == "Dispatcher"
    assert (await client.get("/api/v1/auth/me", headers=officer)).status_code == 401

    dispatcher = auth(await login(client, "officer"))
    disabled = await client.post(
        f"/api/v1/admin/staff/{people['officer'].id}/status",
        headers=admin,
        json={"status": "DISABLED"},
    )
    assert disabled.status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=dispatcher)).status_code == 401
    relogin = await client.post(
        "/api/v1/auth/officers/login", json={"email": "officer@test.dev", "password": PASSWORD}
    )
    assert relogin.status_code == 401


async def test_admin_cannot_lock_themselves_out(client, db):
    _, _, people = await roster(db)
    admin = auth(await login(client, "admin"))
    own_status = await client.post(
        f"/api/v1/admin/staff/{people['admin'].id}/status",
        headers=admin,
        json={"status": "DISABLED"},
    )
    assert own_status.status_code == 403
    own_role = await client.patch(
        f"/api/v1/admin/staff/{people['admin'].id}", headers=admin, json={"role": "OFFICER"}
    )
    assert own_role.status_code == 403


async def test_dispatcher_assigns_within_office_and_auditor_cannot_act(client, db):
    _, _, people = await roster(db)
    report = await create_report(client, await register_and_login(client))
    dispatcher = auth(await login(client, "dispatcher"))
    auditor = auth(await login(client, "auditor"))

    wrong = await client.post(
        f"/api/v1/admin/reports/{report['public_id']}/assign",
        headers=dispatcher,
        json={"officer_id": people["north_officer"].id},
    )
    assert wrong.status_code == 422
    candidates = (
        await client.get(
            f"/api/v1/admin/reports/{report['public_id']}/assignable", headers=dispatcher
        )
    ).json()
    assert {item["name"] for item in candidates} >= {"officer", "dispatcher"}
    assert "auditor" not in {item["name"] for item in candidates}

    assigned = await client.post(
        f"/api/v1/admin/reports/{report['public_id']}/assign",
        headers=dispatcher,
        json={"officer_id": people["officer"].id, "reason": "Closest"},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["status"] == "ASSIGNED"
    assert assigned.json()["assigned_officer"]["name"] == "officer"

    # The assigned officer continues the normal workflow from ASSIGNED.
    officer = auth(await login(client, "officer"))
    responding = await client.post(
        f"/api/v1/officer/reports/{report['public_id']}/respond", headers=officer
    )
    assert responding.status_code == 200

    # Dispatchers cannot force a status; auditors cannot touch anything.
    override = {"status": "CANCELLED", "reason": "Duplicate"}
    url = f"/api/v1/admin/reports/{report['public_id']}"
    assert (
        await client.post(f"{url}/status", headers=dispatcher, json=override)
    ).status_code == 403
    assert (
        await client.post(f"{url}/assign", headers=auditor, json={"officer_id": None})
    ).status_code == 403
    take = await client.post(
        f"/api/v1/officer/reports/{report['public_id']}/acknowledge", headers=auditor
    )
    assert take.status_code == 403

    office_admin = auth(await login(client, "office_admin"))
    cancelled = await client.post(f"{url}/status", headers=office_admin, json=override)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"

    log = (await client.get(f"/api/v1/admin/audit?target_id={report['public_id']}",
                            headers=auditor)).json()
    actions = {item["action"] for item in log["items"]}
    assert {"REPORT_ASSIGNED", "STATUS_OVERRIDDEN"} <= actions
    assigned_entry = next(item for item in log["items"] if item["action"] == "REPORT_ASSIGNED")
    assert assigned_entry["actor_name"] == "dispatcher"


async def test_reports_search_export_and_analytics(client, db):
    await roster(db)
    report = await create_report(client, await register_and_login(client))
    admin = auth(await login(client, "admin"))
    page = (await client.get("/api/v1/admin/reports?search=collided", headers=admin)).json()
    assert page["total"] == 1 and page["items"][0]["public_id"] == report["public_id"]
    north_officer = auth(await login(client, "north_officer"))
    hidden = (await client.get("/api/v1/officer/reports", headers=north_officer)).json()
    assert hidden["total"] == 0

    export = await client.get("/api/v1/admin/reports/export.csv", headers=admin)
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    assert report["public_id"] in export.text

    stats = (await client.get("/api/v1/admin/analytics?days=7", headers=admin)).json()
    assert stats["total"] == 1 and stats["open"] == 1 and stats["unassigned_open"] == 1
    assert len(stats["daily"]) == 7 and stats["daily"][-1]["created"] == 1


async def test_offices_can_be_edited_but_not_all_deactivated(client, db):
    central, north, _ = await roster(db)
    admin = auth(await login(client, "admin"))
    office_admin = auth(await login(client, "office_admin"))
    edit = await client.patch(
        f"/api/v1/admin/offices/{central.id}", headers=office_admin, json={"service_radius": 12}
    )
    assert edit.status_code == 200 and edit.json()["service_radius"] == 12
    assert (
        await client.patch(
            f"/api/v1/admin/offices/{north.id}", headers=office_admin, json={"name": "Zone"}
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/admin/offices/{central.id}", headers=office_admin, json={"active": False}
        )
    ).status_code == 403
    first = await client.patch(
        f"/api/v1/admin/offices/{north.id}", headers=admin, json={"active": False}
    )
    assert first.status_code == 200
    last = await client.patch(
        f"/api/v1/admin/offices/{central.id}", headers=admin, json={"active": False}
    )
    assert last.status_code == 409


async def test_blocked_reporter_cannot_sign_in_to_the_app(client, db):
    await roster(db)
    login_body = {"identifier": "caller@test.dev", "passcode": "1234"}
    first = await client.post("/app/api/v1/auth/login", json=login_body)
    assert first.status_code == 200
    admin = auth(await login(client, "admin"))
    reporters = (await client.get("/api/v1/admin/reporters", headers=admin)).json()
    caller = next(item for item in reporters["items"] if item["email"] == "caller@test.dev")
    blocked = await client.post(
        f"/api/v1/admin/reporters/{caller['id']}/status",
        headers=admin,
        json={"status": "DISABLED", "reason": "Abuse"},
    )
    assert blocked.status_code == 204
    assert (await client.post("/app/api/v1/auth/login", json=login_body)).status_code == 403


async def test_password_change_requires_current_password(client, db):
    await roster(db)
    headers = auth(await login(client, "officer"))
    wrong = await client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": "nope", "new_password": "AnotherPass!234"},
    )
    assert wrong.status_code == 400
    ok = await client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "AnotherPass!234"},
    )
    assert ok.status_code == 204
    relogin = await client.post(
        "/api/v1/auth/officers/login",
        json={"email": "officer@test.dev", "password": "AnotherPass!234"},
    )
    assert relogin.status_code == 200
