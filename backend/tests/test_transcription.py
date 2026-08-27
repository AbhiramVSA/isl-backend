async def test_holistic_model_requires_authentication(client):
    response = await client.get("/api/v1/officer/transcription/model")
    assert response.status_code in {401, 403}
