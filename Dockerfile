# GPU-enabled via tensorflow[and-cuda] (CUDA/cuDNN come in as pip packages),
# so no CUDA base image is needed — just the NVIDIA driver and
# nvidia-container-toolkit on the host, and a GPU reservation at runtime
# (docker-compose.yml provides it). Falls back to CPU if no GPU is visible.
# Note MediaPipe landmark extraction is CPU-only in Python either way; the
# GPU accelerates the LSTM.
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

# Cache mount keeps the multi-GB CUDA wheels out of the image layer while
# letting interrupted builds resume without redownloading.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# Allocate GPU memory as needed instead of TF's default of grabbing nearly
# all VRAM — this model needs a sliver of an A100, and the server is shared.
ENV TF_FORCE_GPU_ALLOW_GROWTH=true

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
