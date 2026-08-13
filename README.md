# Incident Response Platform

A serious prototype that helps officers receive and respond to reports from deaf and hard-of-hearing people. Officers can request a consent-based live camera feed to see the reporting user’s signing. It includes a FastAPI API, SQLite/Alembic data layer, JWT and Argon2id security, geographic office routing, real-time updates, LiveKit integration, evidence uploads, audit history, and a responsive Svelte 5 officer PWA.

## Quick start

Requirements: Python 3.12+, `uv`, Node 20+, and npm.

```bash
cp .env.example backend/.env
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run incident-seed
uv run uvicorn app.main:app --reload
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Development officer: `officer2@example.com` / `OfficerPass!234`. API documentation is at `http://localhost:8000/docs`.

## Verification

```bash
cd backend && uv run pytest && uv run ruff check app tests migrations
cd frontend && npm run check && npm run build
```

## Supporting services

`docker compose up -d` starts Redis and LiveKit. SQLite stays local in `backend/incident.db`; uploaded development evidence stays under `backend/uploads/`. Configure production secrets before any shared deployment.

## Project layout

- `backend/app/api`: thin HTTP and real-time routes
- `backend/app/services`: routing, workflow, notifications, and live state
- `backend/migrations`: Alembic schema history
- `backend/tests`: unit and integrated workflow tests
- `frontend/src/routes`: officer and admin screens
- `frontend/src/lib`: shared API, live updates, map, and UI code
- `android`: Kotlin/Jetpack Compose app for deaf and hard-of-hearing users
- `docs`: architecture, security, mobile integration, and migration guides

SQLite is suitable for this prototype and modest development use. Move to PostgreSQL/PostGIS before heavy multi-office production use; see [database migration](docs/database-migration.md).
