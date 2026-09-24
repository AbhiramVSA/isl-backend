from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# bcrypt only hashes the first 72 bytes, and bcrypt>=5 raises on anything longer.
PASSCODE_MAX_BYTES = 72


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=160)
    passcode: str = Field(default="", max_length=PASSCODE_MAX_BYTES)

    @field_validator("passcode")
    @classmethod
    def _fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > PASSCODE_MAX_BYTES:
            raise ValueError(f"passcode must be at most {PASSCODE_MAX_BYTES} bytes")
        return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    identifier: str
    preferred_language: str


class LoginResponse(BaseModel):
    user: UserResponse
    access_token: str
    expires_at: datetime
