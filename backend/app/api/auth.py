from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.db import get_db
from app.dependencies import Principal, current_principal
from app.models import (
    Account,
    AccountStatus,
    AuditLog,
    Office,
    OfficeMembership,
    RefreshToken,
    Role,
    User,
)
from app.schemas import Identity, LoginRequest, RefreshRequest, TokenPair, UserRegister

router = APIRouter(prefix="/auth", tags=["Authentication"])


async def issue_tokens(db: AsyncSession, account: Account) -> TokenPair:
    access, _ = create_token(
        account.id, account.role, "access", timedelta(minutes=settings.access_token_minutes)
    )
    refresh, jti = create_token(
        account.id, account.role, "refresh", timedelta(days=settings.refresh_token_days)
    )
    db.add(
        RefreshToken(
            token_id=jti,
            account_id=account.id,
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        )
    )
    await db.commit()
    return TokenPair(
        access_token=access, refresh_token=refresh, expires_in=settings.access_token_minutes * 60
    )


async def login(db: AsyncSession, data: LoginRequest, expected_roles: set[Role]) -> TokenPair:
    account = await db.scalar(select(Account).where(Account.email == data.email.lower()))
    if (
        not account
        or account.role not in expected_roles
        or account.status != AccountStatus.ACTIVE
        or not verify_password(data.password, account.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Email or password is incorrect"
        )
    account.last_login_at = datetime.now(UTC)
    db.add(
        AuditLog(
            actor_type=account.role.value,
            actor_id=account.id,
            action="LOGIN",
            target_type="ACCOUNT",
            target_id=str(account.id),
        )
    )
    return await issue_tokens(db, account)


@router.post(
    "/users/register",
    response_model=Identity,
    status_code=201,
    summary="Register a mobile app user",
)
async def register_user(data: UserRegister, db: AsyncSession = Depends(get_db)) -> Identity:
    identity_conditions = [Account.email == data.email.lower()]
    if data.phone:
        identity_conditions.append(Account.phone == data.phone)
    existing = await db.scalar(select(Account.id).where(or_(*identity_conditions)))
    if existing:
        raise HTTPException(status_code=409, detail="An account already exists with these details")
    account = Account(
        email=data.email.lower(),
        phone=data.phone,
        password_hash=hash_password(data.password),
        role=Role.USER,
    )
    db.add(account)
    await db.flush()
    user = User(account_id=account.id, name=data.name.strip(), phone=data.phone)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return Identity(
        id=user.id,
        role=Role.USER,
        name=user.name,
        email=account.email,
        phone=user.phone,
        created_at=account.created_at,
    )


@router.post("/users/login", response_model=TokenPair, summary="Sign in to the mobile app")
async def user_login(data: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    return await login(db, data, {Role.USER})


@router.post(
    "/officers/login", response_model=TokenPair, summary="Sign in to the officer application"
)
async def officer_login(data: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    return await login(db, data, {Role.OFFICER, Role.ADMIN})


@router.post("/refresh", response_model=TokenPair, summary="Rotate a refresh token")
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    payload = decode_token(data.refresh_token, "refresh")
    saved = await db.scalar(select(RefreshToken).where(RefreshToken.token_id == payload["jti"]))
    if not saved or saved.revoked_at or saved.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Please sign in again")
    account = await db.get(Account, saved.account_id)
    if not account or account.status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="Please sign in again")
    saved.revoked_at = datetime.now(UTC)
    pair = await issue_tokens(db, account)
    replacement = decode_token(pair.refresh_token, "refresh")["jti"]
    saved.replaced_by = replacement
    await db.commit()
    return pair


@router.post("/logout", status_code=204, summary="Sign out and revoke a refresh token")
async def logout(data: RefreshRequest, db: AsyncSession = Depends(get_db)) -> None:
    payload = decode_token(data.refresh_token, "refresh")
    saved = await db.scalar(select(RefreshToken).where(RefreshToken.token_id == payload["jti"]))
    if saved and not saved.revoked_at:
        saved.revoked_at = datetime.now(UTC)
        await db.commit()


@router.get("/me", response_model=Identity, summary="Get the signed-in identity")
async def me(
    principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)
) -> Identity:
    profile = principal.user or principal.officer
    office_names: list[str] = []
    office_ids = principal.office_ids
    if principal.officer and principal.account.role != Role.ADMIN:
        ids = await db.scalars(
            select(OfficeMembership.office_id).where(
                OfficeMembership.officer_id == principal.officer.id,
                OfficeMembership.active.is_(True),
            )
        )
        office_ids = tuple(ids.all())
    if office_ids:
        office_names = list(
            (
                await db.scalars(
                    select(Office.name).where(Office.id.in_(office_ids)).order_by(Office.name)
                )
            ).all()
        )
    return Identity(
        id=profile.id if profile else principal.account.id,
        role=principal.account.role,
        name=profile.name if profile else "Administrator",
        email=principal.account.email,
        offices=office_names,
        phone=(profile.phone if principal.user else principal.account.phone),
        created_at=principal.account.created_at,
    )
