# Live video

FastAPI issues report-scoped LiveKit credentials and tracks availability. Pressing the mobile emergency button is the user’s explicit action to create the report and immediately publish camera and microphone media. Officers in the responsible office may subscribe; sensitive viewing is audited. The user always has a visible End Video control.

Run the development services with `docker compose up -d redis livekit egress`. LiveKit carries the live feed and the egress worker writes MP4 recordings under `backend/recordings`. Set a public secure URL and strong credentials in production. Use TURN for difficult mobile networks, short credential lifetimes, TLS, room cleanup, retention controls, and clear consent indicators in the mobile app.
