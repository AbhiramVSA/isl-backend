from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_token
from app.db import get_db
from app.models import Account, AccountStatus, Office, OfficeMembership, Officer, Role, User

bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    account: Account
    user: User | None = None
    officer: Officer | None = None
    office_ids: tuple[int, ...] = ()


async def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    payload = decode_token(credentials.credentials)
    account = await db.get(Account, int(payload["sub"]))
    if (
        not account
        or account.status != AccountStatus.ACTIVE
        or account.role.value != payload.get("role")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    principal = Principal(account=account)
    if account.role == Role.USER:
        principal.user = await db.scalar(select(User).where(User.account_id == account.id))
    else:
        principal.officer = await db.scalar(select(Officer).where(Officer.account_id == account.id))
        global_queue = (
            principal.officer
            and settings.environment == "development"
            and settings.development_global_officer_queue
        )
        if account.role == Role.ADMIN or global_queue:
            ids = await db.scalars(select(Office.id).where(Office.active.is_(True)))
            principal.office_ids = tuple(ids.all())
        elif principal.officer:
            ids = await db.scalars(
                select(OfficeMembership.office_id).where(
                    OfficeMembership.officer_id == principal.officer.id,
                    OfficeMembership.active.is_(True),
                )
            )
            principal.office_ids = tuple(ids.all())
    return principal


def require_roles(*roles: Role):
    async def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.account.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this action",
            )
        return principal

    return dependency


require_user = require_roles(Role.USER)
require_officer = require_roles(Role.OFFICER, Role.ADMIN)
require_admin = require_roles(Role.ADMIN)
