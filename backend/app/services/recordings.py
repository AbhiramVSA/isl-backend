"""Locate saved live-video recordings.

Egress either writes MP4s straight into ``recording_dir`` (shared volume, as in
docker-compose) or, when ``recording_s3_bucket`` is set, uploads them to an
S3-compatible bucket. In the bucket case the file is copied into
``recording_dir`` the first time it is needed, so every caller can keep
working with a local path.
"""

import asyncio
from pathlib import Path

from app.core.config import settings


def s3_enabled() -> bool:
    return bool(settings.recording_s3_bucket)


def _client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.recording_s3_endpoint or None,
        region_name=settings.recording_s3_region,
        aws_access_key_id=settings.recording_s3_access_key_id,
        aws_secret_access_key=settings.recording_s3_secret_access_key,
    )


def _download(key: str, target: Path) -> bool:
    from botocore.exceptions import ClientError

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    try:
        _client().download_file(settings.recording_s3_bucket, key, str(partial))
    except ClientError:
        # Not uploaded yet: egress only uploads once the recording is finalised.
        partial.unlink(missing_ok=True)
        return False
    partial.replace(target)
    return True


async def recording_file(key: str | None) -> Path | None:
    """Return the local path of a finished recording, or None if it isn't ready."""
    if not key:
        return None
    path = settings.recording_dir / key
    if path.is_file():
        return path
    if s3_enabled() and await asyncio.to_thread(_download, key, path):
        return path
    return None
