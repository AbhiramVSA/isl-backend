# Immediate updates and live location

Authenticated officer connections subscribe to their active office memberships. User connections subscribe only to their own profile. The server emits report, assignment, status, location, and live-video availability changes. Payload names are internal and are translated by the PWA into operational wording.

The current process-local hub is appropriate for one development API process. For multiple workers, publish through Redis and keep the same hub interface. Clients reconnect with exponential backoff, refresh their authoritative queue after an event, and never treat a notification as the source of record.

The PWA labels a location as live only when connected and recently updated. After two minutes it becomes “Last known location”; offline cached details are explicitly marked as old.

