# Mobile application API

This is the integration contract for Android and iOS clients. Development base URL: `http://localhost:8000/api/v1`. JSON is used except evidence uploads. Times are ISO 8601 UTC. Treat `public_id` as an opaque report reference.

## Authentication

Send `Authorization: Bearer <access_token>` on protected requests. Access tokens expire after `expires_in` seconds. Store the refresh token in platform secure storage. On a 401, call refresh once, store both newly returned tokens, and retry once. Never decode a token to make authorization decisions.

### Register

`POST /auth/users/register` — public, rate-limited.

```json
{"email":"person@example.com","phone":"9876543210","password":"a-long-password","name":"Person Name"}
```

Returns `201` with `{id, role, name, email}`. Errors: `409` existing email/phone, `422` invalid fields, `429` too many attempts.

### Sign in

`POST /auth/users/login` with `{email, password}`. Returns `{access_token, refresh_token, token_type, expires_in}`. Errors: `401` invalid credentials or disabled account, `429` too many attempts. Mobile users must not call the officer sign-in route.

### Refresh and sign out

`POST /auth/refresh` with `{refresh_token}` rotates the token pair. A refresh token is single-use. `POST /auth/logout` with the refresh token returns `204` and revokes it. If refresh fails with 401, clear credentials and show sign-in.

## Reports

### Create a report

`POST /reports` — registered user required.

```json
{
  "category": "Road Accident",
  "description": "Two vehicles collided. One person may be injured.",
  "latitude": 16.5062,
  "longitude": 80.648,
  "location_accuracy": 7.5,
  "answers": {"injuries": true, "immediate_danger": false}
}
```

Returns `201` with the complete report, selected office, calculated priority, and `NEW` status. The server determines priority and office; do not send either. Errors: `422` invalid GPS/details, `503` no active office, `401` authentication required. Retrying creation can create a second report; the production mobile client should attach a future idempotency key before automatic retries are enabled.

The original coordinates are never changed. `priority` is `CRITICAL`, `HIGH`, or `NORMAL`. Status progresses through `NEW`, `ACKNOWLEDGED`, `RESPONDING`, `ARRIVED`, and `RESOLVED`; clients should display friendly wording.

### Read reports

- `GET /reports/{public_id}` returns the signed-in user's report. `403` means it belongs to someone else; `404` means it does not exist.
- `GET /users/me/reports` returns the user's reports newest first.

Do not infer access from knowing a report reference.

## Location updates

`POST /reports/{public_id}/location` — report owner only.

```json
{"latitude":16.507,"longitude":80.649,"accuracy":5,"speed":2.8,"heading":150,"recorded_at":"2026-08-13T12:00:00Z"}
```

Returns `201` with the stored point. Send only while a report is active and the user has granted location permission. Suggested cadence: every 5–10 seconds while moving, less often while stationary; stop when the report ends or permission is removed. Errors: `403` wrong owner, `404` unknown report, `409` report no longer active, `422` invalid GPS.

## Evidence upload

`POST /reports/{public_id}/media` with `multipart/form-data`, field name `file`. Supported: JPEG, PNG, WebP, MP4, and WebM, up to 25 MiB by default. Returns `{id, media_type, mime_type, size, created_at}`. Errors: `413` too large, `415` unsupported type, `403` wrong owner. Compress large media on-device and do not retry blindly after an uncertain upload result.

## Live video and consent

The user connection may receive a `video.requested` message containing the report reference and consent wording. Show a clear system dialog. Do not open the camera until the user affirmatively accepts.

- `POST /reports/{public_id}/stream/start` — after acceptance. Returns the LiveKit URL and a publisher credential. Join the room with microphone/camera permissions, show a persistent “sharing” indicator, and offer Stop.
- `POST /reports/{public_id}/stream/stop` — stop tracks locally first, then mark the session stopped.
- `GET /reports/{public_id}/stream` — availability for an authorized participant.

Errors: `403` wrong report/office, `404` unknown report, `503` video service unavailable. Never send video frames to FastAPI; publish them to LiveKit.

## Immediate user updates

Connect to `WS /ws/user?access_token=<short-lived-access-token>`. Use TLS (`wss`) outside local development. Messages include:

```json
{"type":"report.updated","report_id":"opaque-reference","status":"RESPONDING"}
```

```json
{"type":"video.requested","report_id":"opaque-reference","message":"An officer is asking to see your signing by live video. Your camera will only start if you accept."}
```

Send `{"type":"ping"}` periodically and expect `pong`. Reconnect with exponential backoff and jitter (1, 2, 4… max 30 seconds). Re-authenticate after token expiry. After reconnecting, fetch the report; messages are hints, not a durable event log. Never show internal message type names to users.

While connected, frequent active-report locations may be sent as `location.update` messages with the same location fields and `report_id`. Wait for `location.accepted`; on `location.rejected`, stop or refresh the report. The HTTP location route remains the reliable fallback on networks that block long-lived connections.

## Common errors

All errors use `{"detail":"safe message"}`; validation errors may include structured field details.

| Status | Meaning | Mobile behavior |
|---|---|---|
| 400 | Invalid action | Correct the request; do not retry automatically |
| 401 | Sign-in required | Refresh once, otherwise sign in |
| 403 | Not permitted | Stop; do not reveal the target |
| 404 | Not found | Refresh the report list |
| 409 | State changed | Fetch current report; show its latest state |
| 413/415 | Evidence rejected | Ask user to choose/compress another file |
| 422 | Invalid fields | Highlight fields; request fresh GPS if relevant |
| 429 | Rate limited | Back off and retry after a delay |
| 503 | Temporary service issue | Keep local draft and let the user retry |

Never show raw status codes or server terminology. Do not log credentials, request bodies containing sensitive descriptions, or precise coordinates in analytics/crash reports.
