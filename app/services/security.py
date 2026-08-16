import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def new_reference_code(report_id: str) -> str:
    """`SOS-4F2A91` — short enough to sign, or to read out over a relay call."""
    tail = "".join(ch for ch in report_id if ch.isalnum())[-6:]
    return f"SOS-{tail.upper()}"


def hash_passcode(passcode: str) -> str:
    return bcrypt.hashpw(passcode.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_passcode(passcode: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(passcode.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # A malformed hash in the database should read as "wrong passcode"
        # rather than blowing up the login endpoint.
        return False


def create_access_token(user_id: str) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_ttl_minutes
    )
    token = jwt.encode(
        {"sub": user_id, "exp": expires_at},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_at


def read_access_token(token: str) -> str | None:
    """Returns the user id, or None when the token is invalid or expired."""
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None


def display_name_from(identifier: str) -> str:
    """Turns "priya.n@mail.com" or "+91 98765 43210" into something addressable."""
    local = identifier.strip().split("@")[0]
    words = [word for word in local.replace("_", " ").replace(".", " ").replace("-", " ").split() if word]
    if not words or not any(char.isalpha() for word in words for char in word):
        return f"Caller {local[-4:]}" if len(local) >= 4 else "Caller"
    return " ".join(word.capitalize() for word in words)
