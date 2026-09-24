# ISL SOS API

FastAPI backend for the [ISL SOS](../isl) emergency-reporting app — a Kotlin
Multiplatform app used by Deaf people in Andhra Pradesh to report emergencies in
Indian Sign Language.

Two jobs:

1. **Sign recognition.** A short video of a sign is uploaded, 45 frames are
   sampled evenly across it, MediaPipe Holistic extracts pose + hand landmarks
   (258 features per frame), and a stacked LSTM classifies the sequence. Ported
   from [Sooryak12/Indian-Sign-Language-Recognition](https://github.com/Sooryak12/Indian-Sign-Language-Recognition).
2. **Everything around the report.** Accounts, storing the reports the app
   writes, the station directory, and an optional proxy to NVIDIA NIM.

The report *prose* is written on the device (by `z-ai/glm-5.2` via NIM, or by the
app's own composer when the model is unreachable). This service stores it — which
is what turns a document on someone's phone into a dispatchable incident.

## Endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health` | — | Whether the recogniser loaded |
| `POST` | `/api/v1/predict` | — | Multipart clip → one recognised word |
| `POST` | `/api/v1/auth/login` | — | Sign in, creating the account on first use |
| `GET` | `/api/v1/auth/me` | ✅ | Check a stored token is still valid |
| `POST` | `/api/v1/reports` | ✅ | **Store a report the app wrote** |
| `GET` | `/api/v1/reports` | ✅ | This caller's history, newest first |
| `GET` | `/api/v1/reports/{id}` | ✅ | One report — how status reaches the caller |
| `PATCH` | `/api/v1/reports/{id}/status` | ✅ | Move it along (see the warning below) |
| `GET` | `/api/v1/stations/nearby` | ✅ | Stations around a point, nearest first |
| `POST` | `/api/v1/llm/chat` | ✅ | Pass-through to NVIDIA NIM |

Auth is `Authorization: Bearer <token>` from `/auth/login`.

Full request/response shapes: [`../isl/docs/BACKEND_API.md`](../isl/docs/BACKEND_API.md).

## Setup

The API half runs on any modern Python. Only the recogniser needs 3.9–3.11,
because TensorFlow 2.15 has no wheels above that.

```bash
python3.11 -m venv .venv && source .venv/bin/activate

# API only — auth, reports, stations, LLM proxy. /predict reports itself
# unavailable via /health and nothing else is affected.
pip install -r requirements-api.txt

# …or the full stack, including sign recognition (needs 3.9-3.11 and ffmpeg):
pip install -r requirements.txt
curl -L -o ml_models/170-0.83.hdf5 \
  "https://raw.githubusercontent.com/Sooryak12/Indian-Sign-Language-Recognition/pycode/lstm-model/170-0.83.hdf5"

cp .env.example .env
```

## Run

```bash
uvicorn app.main:app --reload
```

Tables are created on startup. Interactive docs at `/docs`.

```bash
pytest        # 19 tests, no network or ML stack required
```

## Things that must change before real users

These are all deliberate pilot-grade choices, not oversights. Each one is
commented at its call site too.

**Auth has no ownership check.** The first person to sign in with a given
identifier claims it. The app has no registration flow and someone in an
emergency should not be stopped at a signup form — but an identifier is
therefore not proof of identity. Add OTP verification against the phone number
before this handles real accounts.

**`SECRET_KEY` must be set.** With the built-in default, anyone who has read this
repo can mint a token for any account. The service prints a warning at startup
while the default is in use.

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**The station directory is placeholder data.** `data/police_stations.json` has
real coordinates and **fake phone numbers**. A wrong number on an emergency
screen is worse than no number at all — replace it with the AP Police directory,
or point `STATIONS_FILE` somewhere else. `distance_m` is straight-line, not road
distance.

**`PATCH /reports/{id}/status` has no role check.** Right now a caller could mark
their own incident resolved. It exists because `GET /reports/{id}` lets the
caller watch status change and nothing could change it — gate it behind a
dispatcher role before a control room touches it.

**Nothing is dispatched.** A stored report sits in the database; no one is paged.
See the `TODO` in `app/api/v1/endpoints/reports.py`.

**The recogniser knows three words.** *Hello*, *How are you*, *thank you*. No
distress vocabulary exists yet, so every real emergency currently comes back as
one of those three. Moving report generation to an LLM did not change this — the
model can only reason about the words it is given. This is the highest-value work
left on the project.

## Layout

```
app/
  main.py              app factory: creates tables, loads the model, wires routers
  core/
    config.py          pydantic-settings (reads .env)
    media.py           upload constraints, kept free of heavy imports
  api/
    deps.py            bearer-token → current user
    health.py          GET /health
    v1/
      router.py        aggregates the v1 routers
      endpoints/
        predict.py     POST /api/v1/predict
        auth.py        login, me
        reports.py     submit, list, fetch, status
        stations.py    nearby stations
        llm.py         NVIDIA NIM proxy
  db/                  declarative Base, engine, get_db
  models/              User, Report
  schemas/             request/response models
  services/
    isl.py             inference pipeline (TensorFlow + MediaPipe)
    security.py        hashing, JWTs, id generation
    stations.py        directory loading + distance
data/
  police_stations.json placeholder directory — replace before release
tests/                 19 tests over the API half
ml_models/             LSTM weights (gitignored)
```

## Deploy with Docker

The image runs TensorFlow on the GPU via `tensorflow[and-cuda]` (CUDA 12.2 +
cuDNN 8.9 ship as pip packages inside the image), so the host only needs the
NVIDIA driver (≥ 535) and nvidia-container-toolkit — no CUDA install on the
host. MediaPipe landmark extraction is CPU-only in Python regardless; the GPU
accelerates the LSTM. `TF_FORCE_GPU_ALLOW_GROWTH=true` is set so the
container allocates VRAM as needed instead of TF's default of grabbing nearly
all of it (matters on a shared server). The trained weights are downloaded
into the image at build time, so no manual model download is needed.

Preflight — check Docker can see the GPU:

```bash
docker run --rm --gpus all nvidia/cuda:12.2.2-base-ubuntu22.04 nvidia-smi
```

If that errors with "could not select device driver nvidia", install the
toolkit (root, Ubuntu/Debian):

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -sL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Then deploy (needs Docker with the compose plugin):

```bash
git clone <repo-url> isl-backend
cd isl-backend

# Secrets live in a .env next to docker-compose.yml (never in the image).
# SECRET_KEY is required — with the built-in default anyone can mint tokens.
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" > .env
# optional: echo "NVIDIA_NIM_API_KEY=nvapi-..." >> .env

docker compose up -d --build

# wait for startup (TensorFlow import takes a while), then verify:
curl http://localhost:8100/health
# {"status":"ok","model_loaded":true,"model_error":null,"gpus":["/physical_device:GPU:0"]}
```

An empty `gpus` list means the API is up but fell back to CPU — fix the
toolkit/driver and `docker compose up -d --force-recreate`.

The API is published on **host port 8100** (container-internal 8000). To use a
different host port: `ISL_PORT=9000 docker compose up -d`, or put
`ISL_PORT=9000` in a `.env` file next to `docker-compose.yml`.

Useful afterwards:

```bash
docker compose logs -f          # tail logs
docker compose up -d --build    # redeploy after git pull
docker compose down             # stop (keeps the database)
docker compose down -v          # stop AND delete users + reports
```

The SQLite database (users, reports) lives in the `isl-data` named volume at
`/data/app.db` inside the container, so it survives rebuilds. Back it up with
`docker cp isl-backend:/data/app.db ./app.db.bak`. Set `DATABASE_URL` in `.env`
to use Postgres instead.

The bundled station directory is copied into the image from `data/`. To use the
real one without committing it, bind-mount it and point `STATIONS_FILE` at it:
add `- ./police_stations.local.json:/app/data/police_stations.local.json:ro`
under `volumes:` and `STATIONS_FILE=data/police_stations.local.json` in `.env`.

### For the sysadmin (domain mapping)

- Reverse-proxy the domain to `http://127.0.0.1:8100` (plain HTTP, no websockets).
- Allow large request bodies — clients upload short videos. nginx: `client_max_body_size 50m;`
- Inference takes a few seconds per request; set read timeouts accordingly. nginx: `proxy_read_timeout 120s;`
- Health endpoint for monitoring: `GET /health`.

Once the domain exists, restrict CORS to the frontend origin (default is `*`):
`CORS_ORIGINS=https://your-frontend.example.org` in the `.env` next to
`docker-compose.yml`, then `docker compose up -d` to apply.

## Notes

- `app/services/isl.py` imports OpenCV, MediaPipe and TensorFlow at module load.
  Nothing in the router chain imports it directly — `app/core/media.py` holds the
  upload constraints — so the service starts and serves everything else when the
  CV stack is absent.
- The checkpoint is weights-only; the layer stack is rebuilt in `isl.py` and must
  stay in sync with upstream (LSTM 64→128→256→64, Dense 64→32→3).
- `/predict` is sync (`def`), so FastAPI runs it in the threadpool and MediaPipe
  does not block the event loop.
- Reports deduplicate on `(user_id, client_id)`. Resubmitting returns 200 with the
  existing record instead of filing a second incident — a caller retrying over a
  bad connection must not create two.
