# ISL Recognition API

FastAPI backend serving the word-level Indian Sign Language recognizer from
[Sooryak12/Indian-Sign-Language-Recognition](https://github.com/Sooryak12/Indian-Sign-Language-Recognition).

A short video (2–3 s) of a sign is uploaded, 45 frames are sampled evenly across it,
MediaPipe Holistic extracts pose + hand landmarks (258 features per frame), and a stacked
LSTM classifies the sequence into one of three words: **Hello**, **How are you**, **thank you**.

## Layout

```
app/
  main.py              # app factory: wires routers, loads the model on startup
  core/
    config.py          # pydantic-settings (reads .env)
  api/
    health.py          # GET /health (unversioned, for load balancers)
    v1/
      router.py        # aggregates v1 endpoint routers under /api/v1
      endpoints/
        predict.py     # POST /api/v1/predict
  db/
    base.py            # SQLAlchemy declarative Base
    session.py         # engine, SessionLocal, get_db dependency
  models/              # SQLAlchemy models (empty until persistence is needed)
  schemas/             # Pydantic request/response models
  services/
    isl.py             # inference pipeline ported from the upstream repo
tests/
ml_models/             # put the LSTM weights here (gitignored)
```

## Setup

Python 3.9–3.11 (TensorFlow 2.15 has no wheels for 3.12+). `ffmpeg` must be on the PATH
(sk-video shells out to it to decode uploads).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional, defaults work

# Download the trained LSTM weights (~2.7 MB)
curl -L -o ml_models/170-0.83.hdf5 \
  "https://raw.githubusercontent.com/Sooryak12/Indian-Sign-Language-Recognition/pycode/lstm-model/170-0.83.hdf5"
```

## Run

```bash
uvicorn app.main:app --reload
```

- `GET /health` — reports whether the model loaded (and the error if it didn't)
- `POST /api/v1/predict` — multipart upload of a short sign video (`.mp4`, `.avi`, `.mov`),
  returns the predicted word

```bash
curl -F "file=@hello.mp4" http://localhost:8000/api/v1/predict
# {"label": "Hello"}
```

Videos shorter than 45 frames are zero-padded; longer ones are downsampled to 45 evenly
spaced frames, so any clip of roughly 2–5 seconds works.

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
docker compose down             # stop
```

### For the sysadmin (domain mapping)

- Reverse-proxy the domain to `http://127.0.0.1:8100` (plain HTTP, no websockets).
- Allow large request bodies — clients upload short videos. nginx: `client_max_body_size 50m;`
- Inference takes a few seconds per request; set read timeouts accordingly. nginx: `proxy_read_timeout 120s;`
- Health endpoint for monitoring: `GET /health`.

Once the domain exists, restrict CORS to the frontend origin (default is `*`):
`CORS_ORIGINS=https://your-frontend.example.org` in the `.env` next to
`docker-compose.yml`, then `docker compose up -d` to apply.

## Notes

- The checkpoint (`170-0.83.hdf5`) is weights-only; the layer stack is rebuilt in
  `app/services/isl.py` and must stay in sync with the upstream architecture
  (LSTM 64→128→256→64, Dense 64→32→3).
- Inference is CPU-friendly (~2.7 MB model) but MediaPipe processing of 45 frames takes a
  few seconds per request. The endpoint is sync (`def`), so FastAPI runs it in its
  threadpool without blocking the event loop.
- Upstream pinned `tensorflow==2.13`, which cannot share an environment with pydantic v2
  (conflicting `typing-extensions` pins); `requirements.txt` pins 2.15.1 instead, the last
  Keras-2 release. The weights load unchanged.

## Not wired up yet (on purpose)

- `app/db/` is ready but no tables exist yet — add models under `app/models/`, import them in
  `app/models/__init__.py`, and call `Base.metadata.create_all(engine)` (or add Alembic) when
  you need persistence.
- Celery / Redis / psycopg2 are stubbed as commented lines in `requirements.txt` and `.env.example`.
