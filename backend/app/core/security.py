import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException, status
from pwdlib import PasswordHash

from app.core.config import settings
from app.models import Role

password_hasher = PasswordHash.recommended()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def create_token(
    subject: int, role: Role, kind: str, lifetime: timedelta, token_id: str | None = None
) -> tuple[str, str]:
    jti = token_id or str(uuid.uuid4())
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "role": role.value,
        "type": kind,
        "jti": jti,
        "iat": now,
        "exp": now + lifetime,
        "iss": "incident-platform",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM), jti


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[ALGORITHM], issuer="incident-platform"
        )
        if payload.get("type") != expected_type:
            raise ValueError("incorrect token type")
        return payload
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        ) from exc
