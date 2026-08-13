# Sign Response Android App

Kotlin/Jetpack Compose client for deaf and hard-of-hearing users. It supports registration, login, location permission, and a one-tap emergency report with optional title and description. Pressing the emergency button starts the camera and microphone immediately after permissions are approved; the user has an End Video button.

## Run in Android Studio

1. From the repository root, start live video and recording with `docker compose up -d redis livekit egress`.
2. Start the backend from `backend` with `uv run alembic upgrade head`, then `uv run uvicorn app.main:app --reload --host 0.0.0.0`.
3. Open this `android` directory in Android Studio.
4. Let Gradle sync and install Android SDK 36 if prompted.
5. Run the `app` configuration on an emulator or Android device.

The emulator connects to `http://10.0.2.2:8000` and maps the development video address to the host automatically. For a physical phone, change `API_BASE_URL` in `app/build.gradle.kts` to your computer’s LAN address, such as `http://192.168.1.10:8000/api/v1/`, then rebuild. The phone and computer must share a network, and the backend must use `--host 0.0.0.0`.

Development allows cleartext HTTP for local testing. Production must use HTTPS and should store credentials with Android Keystore-backed encrypted storage.
