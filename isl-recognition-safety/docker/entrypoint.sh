#!/bin/sh
# Downloads any missing model weights into /app/models (a volume), then starts the server.
set -e
cd /app
if [ "${ISL_SKIP_MODEL_DOWNLOAD:-0}" != "1" ]; then
  echo "[entrypoint] checking model weights in /app/models ..."
  python scripts/download_models.py || echo "[entrypoint] WARNING: some downloads failed; those heads will be disabled (see /api/health)"
fi
python - <<'EOF'
import torch
print(f"[entrypoint] torch {torch.__version__} cuda_available={torch.cuda.is_available()}",
      f"device={torch.cuda.get_device_name(0)}" if torch.cuda.is_available() else "(CPU mode)")
EOF
exec "$@"
