# Database

The prototype uses SQLAlchemy 2 async sessions and Alembic against SQLite. Foreign keys and WAL mode are enabled on every SQLite connection. Models use portable types, explicit relationships, indexes for office queues and history, and no SQLite-specific business queries.

Core records are accounts, separate user/officer profiles, offices and memberships, reports, immutable initial report coordinates, append-only locations, report history, evidence metadata, refresh-token state, live-video state, and audit logs. Large files are never placed in SQLite.

Run migrations with `cd backend && uv run alembic upgrade head`. Create a schema change with `uv run alembic revision --autogenerate -m "description"` and inspect generated SQL before applying it.

