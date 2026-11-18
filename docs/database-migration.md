# Migrating to PostgreSQL and PostGIS

1. Back up `incident.db` and stop writes.
2. Provision PostgreSQL, enable `postgis`, create an application role, and require TLS.
3. Install an async PostgreSQL driver and change `DATABASE_URL` to `postgresql+asyncpg://...`.
4. Run `alembic upgrade head` against the empty PostgreSQL database.
5. Export tables in foreign-key order, normalize timestamps to UTC, import, and reset sequences.
6. Compare row counts, foreign-key integrity, sampled reports, histories, and coordinates.
7. Replace only `RoutingService` with a PostGIS implementation using a geography point and jurisdiction polygons. Add GiST indexes and use `ST_Covers` then `ST_Distance`.
8. Run the full suite against PostgreSQL, perform a routing shadow comparison, then switch traffic.
9. Retain the SQLite backup until the acceptance window closes.

Production should also move refresh/revocation and connection fan-out to Redis, evidence to S3-compatible storage, and use a PostgreSQL transaction strategy appropriate for assignment contention.

