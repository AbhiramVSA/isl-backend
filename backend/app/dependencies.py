from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.permissions import GLOBAL_SCOPE_ROLES, Permission, permissions_for
from app.core.security import decode_token
from app.db import get_db
from app.models import (
    Account,
    AccountStatus,
    AuditLog,
    Office,
    OfficeMembership,
    Officer,
    Role,
    User,
)

bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    account: Account
    user: User | None = None
    officer: Officer | None = None
    # Offices whose reports this principal can read. Every active office for
    # global roles (and for everyone under the development global queue).
    office_ids: tuple[int, ...] = ()
    # Offices the principal actually belongs to; what "My offices" means.
    member_office_ids: tuple[int, ...] = ()
    permissions: frozenset[Permission] = field(default_factory=frozenset)

    @property
    def role(self) -> Role:
        return self.account.role

    @property
    def global_scope(self) -> bool:
        return self.account.role in GLOBAL_SCOPE_ROLES

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    def can_access_office(self, office_id: int) -> bool:
        return self.global_scope or office_id in self.office_ids

    def can_manage_office(self, office_id: int) -> bool:
        """Management is tied to real membership, never to the dev global queue."""
        return self.global_scope or office_id in self.member_office_ids


async def member_office_ids(db: AsyncSession, officer: Officer | None) -> tuple[int, ...]:
    if not officer:
        return ()
    ids = await db.scalars(
        select(OfficeMembership.office_id)
        .join(Office, Office.id == OfficeMembership.office_id)
        .where(
            OfficeMembership.officer_id == officer.id,
            OfficeMembership.active.is_(True),
            Office.active.is_(True),
        )
    )
    return tuple(ids.all())


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
    # A role change or a disabled account invalidates every token already issued.
    if (
        not account
        or account.status != AccountStatus.ACTIVE
        or account.role.value != payload.get("role")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    principal = Principal(account=account, permissions=permissions_for(account.role))
    if account.role == Role.USER:
        principal.user = await db.scalar(select(User).where(User.account_id == account.id))
        return principal
    principal.officer = await db.scalar(select(Officer).where(Officer.account_id == account.id))
    principal.member_office_ids = await member_office_ids(db, principal.officer)
    global_queue = (
        principal.officer
        and settings.environment == "development"
        and settings.development_global_officer_queue
    )
    if principal.global_scope or global_queue:
        ids = await db.scalars(select(Office.id).where(Office.active.is_(True)))
        principal.office_ids = tuple(ids.all())
    else:
        principal.office_ids = principal.member_office_ids
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


def require_permission(*permissions: Permission):
    """Allow the request when the principal holds every listed permission."""

    async def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not all(principal.can(item) for item in permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not allow this action",
            )
        return principal

    return dependency


def audit(
    principal: Principal | None,
    action: str,
    target_type: str,
    target_id: str | int | None = None,
    metadata: dict | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Build an audit row. ``actor_id`` is always the account id."""
    return AuditLog(
        actor_type=principal.account.role.value if principal else "SYSTEM",
        actor_id=principal.account.id if principal else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        ip_address=request.client.host if request and request.client else None,
        audit_metadata=metadata or {},
    )


require_user = require_roles(Role.USER)
require_officer = require_permission(Permission.REPORTS_VIEW)
require_admin = require_roles(Role.ADMIN)
