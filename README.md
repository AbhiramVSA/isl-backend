# ISL Recognition API

FastAPI backend serving the Indian Sign Language gesture classifier from
[Karthikeyu/Indian-sign-language-recognition](https://github.com/Karthikeyu/Indian-sign-language-recognition).

> **Note on the model:** the upstream repo does **not** contain an LSTM. Its classifier is a
> classic-CV pipeline — SURF descriptors → KMeans bag-of-visual-words → SVM — shipped as two
> pickles (`mini_kmeans_model.sav`, `svm_model.sav`). That is what `/api/v1/predict` serves.

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
ml_models/             # put the two .sav files here (gitignored)
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional, defaults work

# Download the trained models (~90 MB total)
curl -L -o ml_models/mini_kmeans_model.sav \
  https://raw.githubusercontent.com/Karthikeyu/Indian-sign-language-recognition/master/mini_kmeans_model.sav
curl -L -o ml_models/svm_model.sav \
  https://raw.githubusercontent.com/Karthikeyu/Indian-sign-language-recognition/master/svm_model.sav
```

## Run

```bash
uvicorn app.main:app --reload
```

- `GET /health` — reports whether the model loaded (and the error if it didn't)
- `POST /api/v1/predict` — multipart upload of a hand-gesture image, returns one of 35 labels (`1`–`9`, `A`–`Z`)

```bash
curl -F "file=@gesture.jpg" http://localhost:8000/api/v1/predict
# {"label": "A"}
```

The image should be a fairly tight crop of the hand gesture (upstream used a ~300×325 px
camera ROI); it is resized to 128×128 before feature extraction.

## Known caveats (inherited from upstream)

1. **SURF is patented and disabled in modern OpenCV wheels.** `pip install opencv-contrib-python`
   ships without non-free algorithms, so `cv2.xfeatures2d.SURF_create()` raises an error.
   Options:
   - Build OpenCV from source with `OPENCV_ENABLE_NONFREE=ON`, or
   - Use the last pre-patent-enforcement wheels (`opencv-contrib-python==3.4.2.16`), which
     require Python ≤ 3.7 — and correspondingly older FastAPI/Pydantic pins.

   The API starts either way; `/api/v1/predict` returns 503 with the load error until SURF and
   the model files are available. SIFT is *not* a drop-in replacement (128-dim descriptors vs
   the 64-dim SURF descriptors the KMeans model was trained on).

2. **The pickles were created with an old scikit-learn** (upstream targets Python 2.7-era
   tooling and pins no version). If unpickling fails or warns, try older `scikit-learn` pins
   (e.g. `0.24.x`).

## Not wired up yet (on purpose)

- `app/db/` is ready but no tables exist yet — add models under `app/models/`, import them in
  `app/models/__init__.py`, and call `Base.metadata.create_all(engine)` (or add Alembic) when
  you need persistence.
- Celery / Redis / psycopg2 are stubbed as commented lines in `requirements.txt` and `.env.example`.
