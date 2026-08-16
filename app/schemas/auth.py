from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=160)
    passcode: str = Field(default="", max_length=200)


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
