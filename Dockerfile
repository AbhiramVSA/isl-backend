# CPU-only image on purpose: the LSTM is ~2.7 MB and MediaPipe Holistic (the
# actual per-request bottleneck) runs on CPU in Python, so a GPU base image
# would add gigabytes and host-side nvidia-container-toolkit setup for no gain.
FROM python:3.11-slim-bookworm

# ffmpeg: sk-video shells out to it to decode uploaded videos
# libgl1 + libglib2.0-0: native deps of the OpenCV bundled with mediapipe
# curl: weights download below + container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the trained LSTM weights (~2.7 MB) into the image. If this URL ever
# dies, download the file to ml_models/ on the host, drop ml_models from
# .dockerignore, and replace this RUN with: COPY ml_models ./ml_models
RUN mkdir -p ml_models && \
    curl -fL -o ml_models/170-0.83.hdf5 \
      "https://raw.githubusercontent.com/Sooryak12/Indian-Sign-Language-Recognition/pycode/lstm-model/170-0.83.hdf5"

COPY app ./app

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# start-period is generous because TensorFlow import + model load is slow
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
