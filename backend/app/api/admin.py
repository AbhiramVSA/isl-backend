"""Management API: staff, roles, offices and reporters.

Super admins manage everything. Office admins manage officers and dispatchers
inside the offices they belong to, and only those offices. Auditors and
dispatchers can read but not change.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import revoke_refresh_tokens
from app.core.permissions import (
    GLOBAL_SCOPE_ROLES,
    OFFICE_ADMIN_GRANTABLE,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    STAFF_ROLES,
    Permission,
)
from app.core.security import hash_password
from app.db import get_db
from app.dependencies import Principal, audit, require_permission
from app.models import (
    Account,
    AccountStatus,
    Office,
    OfficeMembership,
    Officer,
    Report,
    ReportStatus,
    Role,
    User,
)
from app.schemas_admin import (
    AccountStatusUpdate,
    OfficeAdminOut,
    OfficeCreate,
    OfficeRef,
    OfficeUpdate,
    Page,
    PasswordReset,
    ReporterOut,
    RoleInfo,
    StaffCreate,
    StaffOut,
    StaffUpdate,
)

router = APIRouter(prefix="/admin", tags=["Administration"])

CLOSED = (ReportStatus.RESOLVED, ReportStatus.CANCELLED)

ROLE_DESCRIPTIONS: dict[Role, str] = {
    Role.OFFICER: "Takes reports routed to their offices and responds on the ground.",
    Role.DISPATCHER: "Watches the queue, assigns reports to officers and sets priority.",
    Role.OFFICE_ADMIN: "Runs their offices: manages officers and dispatchers, overrides reports, "
    "reads the audit log.",
    Role.AUDITOR: "Read-only oversight across every office, including the audit log.",
    Role.ADMIN: "Full control of the platform, including offices and other admins.",
}


# --- helpers ----------------------------------------------------------------


def forbid(detail: str = "Your role does not allow this action") -> HTTPException:
    return HTTPException(status_code=403, detail=detail)


async def office_refs(db: AsyncSession, officer_ids: list[int]) -> dict[int, list[OfficeRef]]:
    result: dict[int, list[OfficeRef]] = {officer_id: [] for officer_id in officer_ids}
    if not officer_ids:
        return result
    rows = await db.execute(
        select(OfficeMembership.officer_id, Office.id, Office.name)
        .join(Office, Office.id == OfficeMembership.office_id)
        .where(OfficeMembership.officer_id.in_(officer_ids), OfficeMembership.active.is_(True))
        .order_by(Office.name)
    )
    for officer_id, office_id, name in rows.all():
        result[officer_id].append(OfficeRef(id=office_id, name=name))
    return result


async def staff_outputs(db: AsyncSession, officers: list[Officer]) -> list[StaffOut]:
    ids = [officer.id for officer in officers]
    offices = await office_refs(db, ids)
    open_counts: dict[int, int] = {}
    if ids:
        rows = await db.execute(
            select(Report.assigned_officer_id, func.count())
            .where(Report.assigned_officer_id.in_(ids), Report.status.not_in(CLOSED))
            .group_by(Report.assigned_officer_id)
        )
        open_counts = dict(rows.all())
    return [
        StaffOut(
            id=officer.id,
            account_id=officer.account_id,
            name=officer.name,
            email=officer.account.email,
            phone=officer.account.phone,
            badge_number=officer.badge_number,
            rank=officer.rank,
            role=officer.account.role,
            role_label=ROLE_LABELS[officer.account.role],
            status=officer.account.status,
            offices=offices.get(officer.id, []),
            open_reports=open_counts.get(officer.id, 0),
            created_at=officer.account.created_at,
            last_login_at=officer.account.last_login_at,
        )
        for officer in officers
    ]


async def load_staff(db: AsyncSession, officer_id: int) -> Officer:
    officer = await db.scalar(
        select(Officer).options(selectinload(Officer.account)).where(Officer.id == officer_id)
    )
    if not officer:
        raise HTTPException(status_code=404, detail="Staff member not found")
    return officer


async def target_office_ids(db: AsyncSession, officer_id: int) -> set[int]:
    rows = await db.scalars(
        select(OfficeMembership.office_id).where(
            OfficeMembership.officer_id == officer_id, OfficeMembership.active.is_(True)
        )
    )
    return set(rows.all())


async def ensure_can_manage(db: AsyncSession, principal: Principal, target: Officer) -> None:
    """Raise unless ``principal`` may change ``target``."""
    if principal.global_scope:
        return
    if target.account.role not in OFFICE_ADMIN_GRANTABLE:
        raise forbid("Only a super admin can change this account")
    shared = await target_office_ids(db, target.id) & set(principal.member_office_ids)
    if not shared:
        raise forbid("This person is not in one of your offices")


def ensure_role_grantable(principal: Principal, role: Role) -> None:
    if role not in STAFF_ROLES:
        raise HTTPException(status_code=422, detail="Choose a staff role")
    if not principal.global_scope and role not in OFFICE_ADMIN_GRANTABLE:
        raise forbid("Only a super admin can grant this role")


async def validate_offices(db: AsyncSession, principal: Principal, office_ids: list[int]) -> None:
    if not office_ids:
        return
    found = set(
        (
            await db.scalars(
                select(Office.id).where(Office.id.in_(office_ids), Office.active.is_(True))
            )
        ).all()
    )
    missing = set(office_ids) - found
    if missing:
        raise HTTPException(status_code=404, detail="One or more offices were not found")
    if not principal.global_scope and not set(office_ids) <= set(principal.member_office_ids):
        raise forbid("You can only assign people to your own offices")


async def set_memberships(
    db: AsyncSession, principal: Principal, officer_id: int, office_ids: list[int]
) -> None:
    """Replace memberships the principal controls; keep any outside their scope."""
    rows = list(
        (
            await db.scalars(
                select(OfficeMembership).where(OfficeMembership.officer_id == officer_id)
            )
        ).all()
    )
    wanted = set(office_ids)
    by_office = {row.office_id: row for row in rows}
    for office_id, row in by_office.items():
        if principal.can_manage_office(office_id):
            row.active = office_id in wanted
    for office_id in wanted - set(by_office):
        db.add(OfficeMembership(office_id=office_id, officer_id=officer_id))


async def active_admin_count(db: AsyncSession) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(Account)
            .where(Account.role == Role.ADMIN, Account.status == AccountStatus.ACTIVE)
        )
        or 0
    )


async def ensure_unique(
    db: AsyncSession,
    email: str | None = None,
    badge: str | None = None,
    phone: str | None = None,
    account_id: int | None = None,
    officer_id: int | None = None,
) -> None:
    if email:
        query = select(Account.id).where(Account.email == email.lower())
        if account_id:
            query = query.where(Account.id != account_id)
        if await db.scalar(query):
            raise HTTPException(status_code=409, detail="An account already uses this email")
    if phone:
        query = select(Account.id).where(Account.phone == phone)
        if account_id:
            query = query.where(Account.id != account_id)
        if await db.scalar(query):
            raise HTTPException(status_code=409, detail="An account already uses this phone number")
    if badge:
        query = select(Officer.id).where(Officer.badge_number == badge)
        if officer_id:
            query = query.where(Officer.id != officer_id)
        if await db.scalar(query):
            raise HTTPException(status_code=409, detail="This badge number is already in use")


# --- roles ------------------------------------------------------------------


@router.get("/roles", response_model=list[RoleInfo], summary="Roles and what they can do")
async def roles(principal: Principal = Depends(require_permission(Permission.STAFF_VIEW))):
    return [
        RoleInfo(
            role=role,
            label=ROLE_LABELS[role],
            description=ROLE_DESCRIPTIONS[role],
            permissions=sorted(item.value for item in ROLE_PERMISSIONS[role]),
            global_scope=role in GLOBAL_SCOPE_ROLES,
            grantable=principal.can(Permission.STAFF_MANAGE)
            and (principal.global_scope or role in OFFICE_ADMIN_GRANTABLE),
        )
        for role in (Role.OFFICER, Role.DISPATCHER, Role.OFFICE_ADMIN, Role.AUDITOR, Role.ADMIN)
    ]


# --- staff ------------------------------------------------------------------


@router.get("/staff", response_model=Page[StaffOut], summary="List staff accounts")
async def list_staff(
    search: str | None = None,
    role: Role | None = None,
    office_id: int | None = None,
    status: AccountStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require_permission(Permission.STAFF_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> Page[StaffOut]:
    query = select(Officer).join(Account, Account.id == Officer.account_id)
    if not principal.global_scope:
        visible = select(OfficeMembership.officer_id).where(
            OfficeMembership.office_id.in_(principal.member_office_ids),
            OfficeMembership.active.is_(True),
        )
        query = query.where(Officer.id.in_(visible))
    if office_id is not None:
        query = query.where(
            Officer.id.in_(
                select(OfficeMembership.officer_id).where(
                    OfficeMembership.office_id == office_id, OfficeMembership.active.is_(True)
                )
            )
        )
    if role:
        query = query.where(Account.role == role)
    if status:
        query = query.where(Account.status == status)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Officer.name.ilike(term),
                Account.email.ilike(term),
                Officer.badge_number.ilike(term),
            )
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.scalars(
        query.options(selectinload(Officer.account))
        .order_by(Officer.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return Page(
        items=await staff_outputs(db, list(rows.all())),
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/staff", response_model=StaffOut, status_code=201, summary="Create a staff account")
async def create_staff(
    data: StaffCreate,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.STAFF_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> StaffOut:
    ensure_role_grantable(principal, data.role)
    if data.role not in GLOBAL_SCOPE_ROLES and not data.office_ids:
        raise HTTPException(status_code=422, detail="Add this person to at least one office")
    await validate_offices(db, principal, data.office_ids)
    badge = (data.badge_number or "").strip() or None
    await ensure_unique(db, email=data.email, badge=badge, phone=data.phone)
    account = Account(
        email=data.email.lower(),
        phone=data.phone or None,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    db.add(account)
    await db.flush()
    officer = Officer(
        account_id=account.id,
        name=data.name.strip(),
        badge_number=badge or f"EQ-{account.id:05d}",
        rank=data.rank,
    )
    db.add(officer)
    await db.flush()
    db.add_all(
        OfficeMembership(office_id=item, officer_id=officer.id) for item in set(data.office_ids)
    )
    db.add(
        audit(
            principal,
            "STAFF_CREATED",
            "STAFF",
            officer.id,
            {"email": account.email, "role": data.role.value, "office_ids": data.office_ids},
            request,
        )
    )
    new_id = officer.id
    await db.commit()
    return (await staff_outputs(db, [await load_staff(db, new_id)]))[0]


@router.get("/staff/{officer_id}", response_model=StaffOut, summary="Get a staff account")
async def get_staff(
    officer_id: int,
    principal: Principal = Depends(require_permission(Permission.STAFF_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> StaffOut:
    officer = await load_staff(db, officer_id)
    if not principal.global_scope and not (
        await target_office_ids(db, officer.id) & set(principal.member_office_ids)
    ):
        raise HTTPException(status_code=404, detail="Staff member not found")
    return (await staff_outputs(db, [officer]))[0]


@router.patch("/staff/{officer_id}", response_model=StaffOut, summary="Edit a staff account")
async def update_staff(
    officer_id: int,
    data: StaffUpdate,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.STAFF_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> StaffOut:
    officer = await load_staff(db, officer_id)
    account = officer.account
    is_self = account.id == principal.account.id
    if not is_self:
        await ensure_can_manage(db, principal, officer)
    changes = data.model_dump(exclude_unset=True)
    if "role" in changes and data.role and data.role != account.role:
        if is_self:
            raise forbid("You cannot change your own role")
        ensure_role_grantable(principal, data.role)
        if account.role == Role.ADMIN and await active_admin_count(db) <= 1:
            raise HTTPException(status_code=409, detail="At least one super admin must remain")
    if data.office_ids is not None:
        await validate_offices(db, principal, data.office_ids)
    await ensure_unique(
        db,
        email=data.email if "email" in changes else None,
        badge=data.badge_number if "badge_number" in changes else None,
        phone=data.phone if "phone" in changes else None,
        account_id=account.id,
        officer_id=officer.id,
    )
    revoke = False
    if "email" in changes and data.email:
        account.email = data.email.lower()
    if "phone" in changes:
        account.phone = data.phone or None
    if "name" in changes and data.name:
        officer.name = data.name.strip()
    if "badge_number" in changes and data.badge_number:
        officer.badge_number = data.badge_number.strip()
    if "rank" in changes:
        officer.rank = data.rank or None
    if "role" in changes and data.role and data.role != account.role:
        account.role = data.role
        revoke = True  # the old token's role no longer matches; force a fresh sign-in
    if data.office_ids is not None:
        await set_memberships(db, principal, officer.id, data.office_ids)
    if revoke:
        await revoke_refresh_tokens(db, account.id)
    db.add(
        audit(
            principal,
            "STAFF_UPDATED",
            "STAFF",
            officer.id,
            {"fields": sorted(changes)} | ({"role": data.role.value} if data.role else {}),
            request,
        )
    )
    await db.commit()
    db.expire_all()
    return (await staff_outputs(db, [await load_staff(db, officer_id)]))[0]


@router.post(
    "/staff/{officer_id}/status", response_model=StaffOut, summary="Enable or disable an account"
)
async def set_staff_status(
    officer_id: int,
    data: AccountStatusUpdate,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.STAFF_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> StaffOut:
    officer = await load_staff(db, officer_id)
    account = officer.account
    if account.id == principal.account.id:
        raise forbid("You cannot change the status of your own account")
    await ensure_can_manage(db, principal, officer)
    if (
        data.status == AccountStatus.DISABLED
        and account.role == Role.ADMIN
        and account.status == AccountStatus.ACTIVE
        and await active_admin_count(db) <= 1
    ):
        raise HTTPException(status_code=409, detail="At least one super admin must remain")
    account.status = data.status
    officer.active = data.status == AccountStatus.ACTIVE
    if data.status == AccountStatus.DISABLED:
        await revoke_refresh_tokens(db, account.id)
    db.add(
        audit(
            principal,
            "STAFF_DISABLED" if data.status == AccountStatus.DISABLED else "STAFF_ENABLED",
            "STAFF",
            officer.id,
            {"reason": data.reason} if data.reason else {},
            request,
        )
    )
    await db.commit()
    db.expire_all()
    return (await staff_outputs(db, [await load_staff(db, officer_id)]))[0]


@router.post("/staff/{officer_id}/password", status_code=204, summary="Reset a staff password")
async def reset_staff_password(
    officer_id: int,
    data: PasswordReset,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.STAFF_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> None:
    officer = await load_staff(db, officer_id)
    if officer.account.id != principal.account.id:
        await ensure_can_manage(db, principal, officer)
    officer.account.password_hash = hash_password(data.password)
    await revoke_refresh_tokens(db, officer.account.id)
    db.add(audit(principal, "STAFF_PASSWORD_RESET", "STAFF", officer.id, request=request))
    await db.commit()


# --- offices ----------------------------------------------------------------


async def office_outputs(db: AsyncSession, offices: list[Office]) -> list[OfficeAdminOut]:
    ids = [office.id for office in offices]
    if not ids:
        return []
    staff = dict(
        (
            await db.execute(
                select(OfficeMembership.office_id, func.count())
                .join(Officer, Officer.id == OfficeMembership.officer_id)
                .join(Account, Account.id == Officer.account_id)
                .where(
                    OfficeMembership.office_id.in_(ids),
                    OfficeMembership.active.is_(True),
                    Account.status == AccountStatus.ACTIVE,
                )
                .group_by(OfficeMembership.office_id)
            )
        ).all()
    )
    totals = dict(
        (
            await db.execute(
                select(Report.office_id, func.count())
                .where(Report.office_id.in_(ids))
                .group_by(Report.office_id)
            )
        ).all()
    )
    open_counts = dict(
        (
            await db.execute(
                select(Report.office_id, func.count())
                .where(Report.office_id.in_(ids), Report.status.not_in(CLOSED))
                .group_by(Report.office_id)
            )
        ).all()
    )
    return [
        OfficeAdminOut.model_validate(office).model_copy(
            update={
                "staff_count": staff.get(office.id, 0),
                "open_reports": open_counts.get(office.id, 0),
                "total_reports": totals.get(office.id, 0),
            }
        )
        for office in offices
    ]


@router.get("/offices", response_model=list[OfficeAdminOut], summary="List offices")
async def list_offices(
    include_inactive: bool = True,
    principal: Principal = Depends(require_permission(Permission.OFFICES_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> list[OfficeAdminOut]:
    query = select(Office).order_by(Office.name)
    if not principal.global_scope:
        query = query.where(Office.id.in_(principal.office_ids))
    if not include_inactive:
        query = query.where(Office.active.is_(True))
    return await office_outputs(db, list((await db.scalars(query)).all()))


@router.post("/offices", response_model=OfficeAdminOut, status_code=201, summary="Create an office")
async def create_office(
    data: OfficeCreate,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.OFFICES_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> OfficeAdminOut:
    if await db.scalar(select(Office.id).where(func.lower(Office.name) == data.name.lower())):
        raise HTTPException(status_code=409, detail="An office with this name already exists")
    office = Office(**data.model_dump())
    db.add(office)
    await db.flush()
    db.add(audit(principal, "OFFICE_CREATED", "OFFICE", office.id, {"name": office.name}, request))
    await db.commit()
    await db.refresh(office)
    return (await office_outputs(db, [office]))[0]


@router.patch("/offices/{office_id}", response_model=OfficeAdminOut, summary="Edit an office")
async def update_office(
    office_id: int,
    data: OfficeUpdate,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.OFFICES_EDIT)),
    db: AsyncSession = Depends(get_db),
) -> OfficeAdminOut:
    office = await db.get(Office, office_id)
    if not office:
        raise HTTPException(status_code=404, detail="Office not found")
    if not principal.can_manage_office(office_id):
        raise forbid("You can only edit your own offices")
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if "active" in changes and changes["active"] != office.active:
        if not principal.can(Permission.OFFICES_MANAGE):
            raise forbid("Only a super admin can activate or deactivate offices")
        if not changes["active"]:
            others = await db.scalar(
                select(func.count())
                .select_from(Office)
                .where(Office.active.is_(True), Office.id != office.id)
            )
            if not others:
                raise HTTPException(
                    status_code=409,
                    detail="This is the last active office; new reports would have nowhere to go",
                )
    if "name" in changes and await db.scalar(
        select(Office.id).where(
            func.lower(Office.name) == changes["name"].lower(), Office.id != office.id
        )
    ):
        raise HTTPException(status_code=409, detail="An office with this name already exists")
    for key, value in changes.items():
        setattr(office, key, value)
    action = "OFFICE_UPDATED"
    if changes.get("active") is False:
        action = "OFFICE_DEACTIVATED"
    elif changes.get("active") is True:
        action = "OFFICE_ACTIVATED"
    db.add(audit(principal, action, "OFFICE", office.id, {"fields": sorted(changes)}, request))
    await db.commit()
    await db.refresh(office)
    return (await office_outputs(db, [office]))[0]


# --- reporters --------------------------------------------------------------


@router.get("/reporters", response_model=Page[ReporterOut], summary="List Equal app reporters")
async def list_reporters(
    search: str | None = None,
    status: AccountStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    principal: Principal = Depends(require_permission(Permission.REPORTERS_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> Page[ReporterOut]:
    query = select(User).join(Account, Account.id == User.account_id)
    if not principal.global_scope:
        # Office admins see the people who have reported to their offices.
        query = query.where(
            User.id.in_(
                select(Report.user_id).where(Report.office_id.in_(principal.member_office_ids))
            )
        )
    if status:
        query = query.where(Account.status == status)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            or_(User.name.ilike(term), Account.email.ilike(term), User.phone.ilike(term))
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    users = list(
        (
            await db.scalars(
                query.options(selectinload(User.account))
                .order_by(Account.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    ids = [user.id for user in users]
    totals: dict[int, int] = {}
    opened: dict[int, int] = {}
    if ids:
        totals = dict(
            (
                await db.execute(
                    select(Report.user_id, func.count())
                    .where(Report.user_id.in_(ids))
                    .group_by(Report.user_id)
                )
            ).all()
        )
        opened = dict(
            (
                await db.execute(
                    select(Report.user_id, func.count())
                    .where(Report.user_id.in_(ids), Report.status.not_in(CLOSED))
                    .group_by(Report.user_id)
                )
            ).all()
        )
    return Page(
        items=[
            ReporterOut(
                id=user.id,
                account_id=user.account_id,
                name=user.name,
                email=user.account.email,
                phone=user.phone or user.account.phone,
                status=user.account.status,
                created_at=user.account.created_at,
                last_login_at=user.account.last_login_at,
                total_reports=totals.get(user.id, 0),
                open_reports=opened.get(user.id, 0),
            )
            for user in users
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/reporters/{user_id}/status", status_code=204, summary="Block or unblock a reporter")
async def set_reporter_status(
    user_id: int,
    data: AccountStatusUpdate,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.REPORTERS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> None:
    user = await db.scalar(
        select(User).options(selectinload(User.account)).where(User.id == user_id)
    )
    if not user:
        raise HTTPException(status_code=404, detail="Reporter not found")
    user.account.status = data.status
    if data.status == AccountStatus.DISABLED:
        await revoke_refresh_tokens(db, user.account.id)
    db.add(
        audit(
            principal,
            "REPORTER_DISABLED" if data.status == AccountStatus.DISABLED else "REPORTER_ENABLED",
            "REPORTER",
            user.id,
            {"reason": data.reason} if data.reason else {},
            request,
        )
    )
    await db.commit()
