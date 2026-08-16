def test_first_login_creates_the_account(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "priya.n@mail.com", "passcode": "hunter2"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["id"].startswith("usr_")
    assert body["user"]["display_name"] == "Priya N"
    assert body["user"]["preferred_language"] == "Indian Sign Language"
    assert body["access_token"]


def test_second_login_requires_the_same_passcode(client):
    client.post(
        "/api/v1/auth/login",
        json={"identifier": "priya.n@mail.com", "passcode": "hunter2"},
    )

    wrong = client.post(
        "/api/v1/auth/login",
        json={"identifier": "priya.n@mail.com", "passcode": "not-it"},
    )
    right = client.post(
        "/api/v1/auth/login",
        json={"identifier": "priya.n@mail.com", "passcode": "hunter2"},
    )

    assert wrong.status_code == 401
    assert right.status_code == 200


def test_login_is_stable_for_the_same_identifier(client):
    first = client.post(
        "/api/v1/auth/login", json={"identifier": "+919876543210", "passcode": "p"}
    ).json()
    second = client.post(
        "/api/v1/auth/login", json={"identifier": "+919876543210", "passcode": "p"}
    ).json()

    assert first["user"]["id"] == second["user"]["id"]


def test_me_rejects_a_junk_token(client):
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )

    assert response.status_code == 401


def test_stations_are_sorted_by_distance_from_the_caller(client, auth_headers):
    response = client.get(
        "/api/v1/stations/nearby",
        params={"lat": 16.5261, "lon": 80.4694},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    stations = response.json()["stations"]
    assert stations, "the bundled directory should not be empty"
    # Asked from Thullur's own coordinates, Thullur must come first.
    assert stations[0]["id"] == "ps-thullur"
    assert stations[0]["distance_m"] == 0
    assert [s["distance_m"] for s in stations] == sorted(
        s["distance_m"] for s in stations
    )


def test_distance_changes_with_the_supplied_point(client, auth_headers):
    from_thullur = client.get(
        "/api/v1/stations/nearby",
        params={"lat": 16.5261, "lon": 80.4694},
        headers=auth_headers,
    ).json()["stations"]
    from_mangalagiri = client.get(
        "/api/v1/stations/nearby",
        params={"lat": 16.4307, "lon": 80.5680},
        headers=auth_headers,
    ).json()["stations"]

    assert from_thullur[0]["id"] != from_mangalagiri[0]["id"]


def test_stations_reject_an_impossible_coordinate(client, auth_headers):
    response = client.get(
        "/api/v1/stations/nearby",
        params={"lat": 999, "lon": 0},
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_llm_proxy_reports_itself_unconfigured_rather_than_failing_oddly(
    client, auth_headers
):
    """Without a server-side key the proxy must say so, not 500."""
    response = client.post(
        "/api/v1/llm/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers=auth_headers,
    )

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_llm_proxy_requires_authentication(client):
    response = client.post(
        "/api/v1/llm/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 401


def test_health_still_reports_the_recogniser(client):
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert "model_loaded" in body
