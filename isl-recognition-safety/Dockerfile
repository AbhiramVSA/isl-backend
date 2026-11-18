# ISL pipeline inspector — single image: FastAPI backend + built React frontend.
# GPU: PyTorch CUDA 12.6 wheels; the host only needs an NVIDIA driver (>= 560) and the
# NVIDIA Container Toolkit. MediaPipe runs on CPU inside the container (as on every platform).
#
#   docker compose up -d --build        # then open http://localhost:8000
#
# Model weights (~600 MB) are downloaded on first start into the ./models volume.

# ---------- stage 1: frontend ----------
FROM node:20-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
COPY frontend/scripts ./scripts
RUN npm ci --ignore-scripts
COPY frontend ./
# copies the MediaPipe WASM runtime into public/; the .task model itself is served by the
# backend from the models volume (GET /models/holistic_landmarker.task)
RUN node scripts/copy-wasm.mjs && npx vite build

# ---------- stage 2: backend ----------
FROM python:3.12-slim-bookworm AS backend
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DEBIAN_FRONTEND=noninteractive
# libegl1/libgles2/libopengl0: MediaPipe's Linux wheel links against EGL even for CPU inference
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libegl1 libgles2 libopengl0 libglib2.0-0 libgomp1 curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# PyTorch first (CUDA 12.6 wheels; override TORCH_INDEX for CPU-only: https://download.pytorch.org/whl/cpu)
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu126
RUN pip install --index-url ${TORCH_INDEX} torch
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY backend ./backend
COPY scripts ./scripts
COPY models/hwgat/class_map_FDMSE.csv ./models/hwgat/
COPY models/include/label_map_include.json models/include/label_map_include50.json ./models/include/
COPY models/openhands/include_slgcn_classes.json ./models/openhands/
COPY docs ./docs
COPY README.md .env.example ./
COPY --from=frontend /build/frontend/dist ./frontend/dist
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health >/dev/null || exit 1
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "backend"]
