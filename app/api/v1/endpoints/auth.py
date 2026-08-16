from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.auth import LoginRequest, LoginResponse, UserResponse
from app.services.security import (
    create_access_token,
    display_name_from,
    hash_passcode,
    new_id,
    verify_passcode,
)

router = APIRouter()


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Signs a caller in, creating the account on first use.

    ⚠️ There is no registration or ownership check: the first person to sign in
    with a given identifier claims it. That is deliberate for a pilot — the app
    has no registration flow and someone in an emergency should not be blocked
    at a signup form — but it means an identifier is not proof of identity.
    Add OTP verification against the phone number before this handles real
    accounts. See README, "Auth is pilot-grade".
    """
    identifier = payload.identifier.strip()
    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter a phone number, email, or ID to continue.",
        )

    user = db.scalar(select(User).where(User.identifier == identifier))

    if user is None:
        user = User(
            id=new_id("usr"),
            identifier=identifier,
            display_name=display_name_from(identifier),
            passcode_hash=hash_passcode(payload.passcode),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not verify_passcode(payload.passcode, user.passcode_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Those sign-in details weren't accepted.",
        )

    token, expires_at = create_access_token(user.id)
    return LoginResponse(
        user=UserResponse.model_validate(user),
        access_token=token,
        expires_at=expires_at,
    )


@router.get("/auth/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> UserResponse:
    """Lets the app check a stored token is still good before trusting it."""
    return UserResponse.model_validate(user)
