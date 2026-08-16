"""The report endpoints.

Storing a report is what turns a document on someone's phone into a dispatchable
incident, so these cover the things that would silently lose or duplicate one.
"""


def test_submit_returns_server_owned_fields(client, auth_headers, submission):
    response = client.post("/api/v1/reports", json=submission, headers=auth_headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"].startswith("rpt_")
    assert body["reference_code"].startswith("SOS-")
    assert body["status"] == "Submitted"
    # Content survives untouched.
    assert body["summary"] == submission["summary"]
    assert body["recommended_actions"] == submission["recommended_actions"]
    assert body["latitude"] == submission["latitude"]
    assert body["generated_by"] == "z-ai/glm-5.2"


def test_resubmitting_the_same_client_id_does_not_file_twice(
    client, auth_headers, submission
):
    """A retry over a flaky connection must not create a second incident."""
    first = client.post("/api/v1/reports", json=submission, headers=auth_headers)
    second = client.post("/api/v1/reports", json=submission, headers=auth_headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    listing = client.get("/api/v1/reports", headers=auth_headers)
    assert len(listing.json()["reports"]) == 1


def test_client_cannot_set_status_or_reference_code(client, auth_headers, submission):
    response = client.post(
        "/api/v1/reports",
        json={**submission, "status": "Resolved", "reference_code": "SOS-HACKED"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["status"] == "Submitted"
    assert response.json()["reference_code"] != "SOS-HACKED"


def test_unknown_category_is_rejected(client, auth_headers, submission):
    response = client.post(
        "/api/v1/reports",
        json={**submission, "category": "Alien Invasion"},
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_oversized_analysis_is_rejected(client, auth_headers, submission):
    response = client.post(
        "/api/v1/reports",
        json={**submission, "situation_analysis": "x" * 20_001},
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_list_is_newest_first(client, auth_headers, submission):
    client.post(
        "/api/v1/reports",
        json={**submission, "client_id": "a", "created_at": "2026-08-01T00:00:00Z"},
        headers=auth_headers,
    )
    client.post(
        "/api/v1/reports",
        json={**submission, "client_id": "b", "created_at": "2026-08-14T00:00:00Z"},
        headers=auth_headers,
    )

    reports = client.get("/api/v1/reports", headers=auth_headers).json()["reports"]

    assert [report["created_at"][:10] for report in reports] == [
        "2026-08-14",
        "2026-08-01",
    ]


def test_status_moves_and_is_visible_to_the_caller(client, auth_headers, submission):
    created = client.post(
        "/api/v1/reports", json=submission, headers=auth_headers
    ).json()

    patched = client.patch(
        f"/api/v1/reports/{created['id']}/status",
        json={"status": "UnitDispatched"},
        headers=auth_headers,
    )
    assert patched.status_code == 200

    fetched = client.get(f"/api/v1/reports/{created['id']}", headers=auth_headers)
    assert fetched.json()["status"] == "UnitDispatched"


def test_reports_are_not_readable_by_another_account(client, auth_headers, submission):
    created = client.post(
        "/api/v1/reports", json=submission, headers=auth_headers
    ).json()

    other = client.post(
        "/api/v1/auth/login",
        json={"identifier": "someone.else@mail.com", "passcode": "x"},
    ).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}

    # 404 rather than 403 — otherwise this endpoint confirms which ids exist.
    assert client.get(
        f"/api/v1/reports/{created['id']}", headers=other_headers
    ).status_code == 404
    assert client.get("/api/v1/reports", headers=other_headers).json()["reports"] == []


def test_reports_require_authentication(client, submission):
    assert client.post("/api/v1/reports", json=submission).status_code == 401
    assert client.get("/api/v1/reports").status_code == 401
