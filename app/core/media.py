"""Upload constraints, kept free of heavy imports.

`app/services/isl.py` pulls in OpenCV, MediaPipe and TensorFlow at import time.
The endpoint only needs to know which containers are acceptable, and `main.py`
is written so a missing CV stack degrades `/predict` rather than taking the whole
service down — that only holds if the router can be imported without it.
"""

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov"}
