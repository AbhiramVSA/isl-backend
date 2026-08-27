async def test_saved_video_transcription_requires_authentication(client):
    response = await client.post("/api/v1/reports/missing/transcription")
    assert response.status_code in {401, 403}
