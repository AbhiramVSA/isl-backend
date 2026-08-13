# Security

Controls implemented in the prototype include Argon2id hashes, short access tokens, rotating/revocable refresh tokens, server-side roles, office/ownership/assignment authorization, authenticated live connections, input and GPS validation, evidence MIME allow-list and size limits, CORS allow-list, response hardening headers, rate limiting, atomic assignment, generic server errors, report history, and audit logs.

Before production: put the API behind TLS and a hardened gateway; use managed secrets; move rate limits and revocation to Redis; use malware scanning and signed object-storage URLs; validate media by file signature; apply retention and legal-hold policy; encrypt backups; add alerting and audit export; conduct penetration and privacy reviews; and deploy PostgreSQL/PostGIS with least-privilege roles.

Location, identity, evidence, and video are sensitive. Logs must not include credentials, raw request bodies, or unnecessary coordinates. Access reviews and officer deactivation must be operational procedures, not only application features.
