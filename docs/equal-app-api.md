# Equal app API

The [Equal](https://github.com/Udhay-Adithya/isl) Kotlin Multiplatform app speaks
a different dialect from the clients in [mobile-api.md](mobile-api.md), so it is
served on its own mount rather than bent into the existing routes.

**Base address: `https://<host>/app`** — everything below hangs off that.

## Why a separate mount

Three of the app's routes collide with ones this service already serves, and in
each case the two shapes cannot both be the answer:

| Route | This service returns | The app requires |
| --- | --- | --- |
| `POST /reports` | `ReportCreate`: a category and a description | a written document: title, severity, situation analysis, recommended actions, transcript |
| `GET /reports/{id}` | `status` in seven values, `id` an integer | `status` in five values, `id` a string |
| `GET /auth/me` | `Identity`: `id` integer, `email` | `id` string, `display_name`, `identifier` |

Serving both from one path would mean breaking one client to satisfy the other.
The app's base address is runtime configuration — set under *Profile → Emergency
service* — so pointing it at `/app` costs nothing on the client side, and the
console's own API is left exactly as it was.

## Endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/app/health` | — | Whether the transcription model can run |
| `POST` | `/app/api/v1/predict` | — | One signing clip → one recognised word |
| `WS` | `/app/api/v1/stream/landmarks` | — | Live landmarks → live glosses (preferred) |
| `WS` | `/app/api/v1/stream/video` | — | Live JPEG frames → live glosses (fallback) |
| `GET` | `/app/api/v1/stream/{id}/draft?token=` | — | Transcript saved when a stream closed |
| `POST` | `/app/api/v1/auth/login` | — | Sign in, creating the account on first use |
| `GET` | `/app/api/v1/auth/me` | ✅ | Check a stored token is still valid |
| `POST` | `/app/api/v1/reports` | ✅ | **Store a report the app wrote** |
| `GET` | `/app/api/v1/reports` | ✅ | This caller's reports, newest first |
| `GET` | `/app/api/v1/reports/{id}` | ✅ | One report — how status reaches the caller |
| `GET` | `/app/api/v1/stations/nearby` | ✅ | Response offices around a point |
| `POST` | `/app/api/v1/llm/chat` | ✅ | Pass-through to NVIDIA NIM |

Reports are addressed by reference code (`SOS-4F2A91`) or by the `rpt_<id>` the
app was handed at submission; either resolves.

## The two dialects

Every conversion lives in `app/services/mobile_reports.py`.

| | Equal app | This service |
| --- | --- | --- |
| Urgency | `severity`: Critical / High / Moderate / Low | `priority`: CRITICAL / HIGH / NORMAL |
| Progress | `status`: Draft / Submitted / Acknowledged / UnitDispatched / Resolved | `status`: NEW / ACKNOWLEDGED / ASSIGNED / RESPONDING / ARRIVED / RESOLVED / CANCELLED |
| Prose | `summary` + `situation_analysis` + `recommended_actions` | `description` |
| Identity | `id` string, `identifier` (phone, email, or ID) | `id` integer, `email` |

Status is the conversion that matters. The app understands five values and
degrades anything else to "Submitted" — so sending `RESPONDING` raw would show
the caller their report sliding *backwards*. Responding and arrived are both
folded onto `UnitDispatched`: from the point of view of someone waiting, a unit
on the way and a unit outside are the same news.

Reports filed here land in the same `reports` table the console reads, routed to
the nearest office by the existing `RoutingService`, and raise the same
`report.created` realtime event. An officer sees them in their queue with no
further work.

## Recognition

`POST /app/api/v1/predict` takes `multipart/form-data` with one part named
**`file`**, filename ending `.mp4`, `.mov`, `.avi`, or `.webm`.

```json
{ "label": "Hello", "confidence": 0.83 }
```

It adapts the same transcriber behind `POST /api/v1/officer/transcription`,
which answers with a full word-timed transcript. The app treats one response as
one sign and stitches multi-word messages from several clips itself, so this
returns the highest-confidence word rather than the joined transcript — sending
the whole string would make the app count a clip twice.

Unauthenticated, because the app records before anyone signs in and a person in
trouble should not meet a login screen first. The service-wide rate limit is
what stands between that and an open door to a subprocess; tighten
`write_requests_per_minute` before this is public.

## Live streaming

For decode-while-streaming, open `WS /app/api/v1/stream/landmarks`
(on-device MediaPipe) or `WS /app/api/v1/stream/video` (JPEG frames) instead
of uploading clips — same unauthenticated model, per-IP/per-kind caps plus
per-stream budgets as the abuse control, transcript saved as a draft for the
report POST. Full wire protocol, budgets, and Android snippets:
[mobile-streaming.md](mobile-streaming.md).

## Sign-in

`POST /app/api/v1/auth/login` takes `{identifier, passcode}`, where the
identifier is a phone number, an email, or an ID issued by a disability-services
office. It is stored in `accounts.email`, which is a plain string column.

> ⚠️ **No ownership check.** The first person to sign in with a given identifier
> claims it. That is deliberate for a pilot — the app has no registration flow
> and someone in an emergency should not be stopped at a signup form — but an
> identifier is not proof of identity. Add OTP verification before real accounts.

Tokens here last `MOBILE_ACCESS_TOKEN_DAYS` (30 by default), not the console's
15 minutes: the app holds a single token and has no refresh flow, and being
signed out mid-emergency is not a failure worth designing in.

## Configuration

```bash
MOBILE_ACCESS_TOKEN_DAYS=30
NVIDIA_NIM_API_KEY=nvapi-xxxxxxxxxxxxxxxx   # unset → /llm/chat answers 503
NIM_DEFAULT_MODEL=meta/muse-glimmer-30b
```

Without a NIM key the app keeps calling NVIDIA directly with the key compiled
into its binary, which is extractable from the APK. Setting it here is what
moves that key server-side.
