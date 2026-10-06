import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.security import hash_password
from app.db import SessionLocal
from app.models import (
    Account,
    Office,
    OfficeMembership,
    Officer,
    Priority,
    Report,
    ReportHistory,
    ReportStatus,
    Role,
    User,
)

DEMO_PASSWORDS = {
    Role.ADMIN: "AdminPass!234",
    Role.OFFICE_ADMIN: "OfficeAdminPass!234",
    Role.DISPATCHER: "DispatcherPass!234",
    Role.AUDITOR: "AuditorPass!234",
    Role.OFFICER: "OfficerPass!234",
}
# email, display name, role, index of the office they belong to (None: every office)
DEMO_STAFF = (
    ("admin@example.com", "Super Admin", Role.ADMIN, None),
    ("officeadmin@example.com", "Office Admin", Role.OFFICE_ADMIN, 0),
    ("dispatcher@example.com", "Dispatcher", Role.DISPATCHER, 0),
    ("auditor@example.com", "Auditor", Role.AUDITOR, None),
)


async def ensure_demo_staff(db, offices: list[Office]) -> None:
    """Bring a development database up to the current demo roster.

    Safe to re-run: renames the seeded officers to "Officer N", gives every
    staff account a profile, and adds any missing role accounts.
    """
    for index in range(1, 5):
        officer = await db.scalar(
            select(Officer)
            .join(Account, Account.id == Officer.account_id)
            .where(Account.email == f"officer{index}@example.com")
        )
        if officer:
            officer.name = f"Officer {index}"
    for email, name, role, office_index in DEMO_STAFF:
        account = await db.scalar(select(Account).where(Account.email == email))
        if not account:
            account = Account(
                email=email, password_hash=hash_password(DEMO_PASSWORDS[role]), role=role
            )
            db.add(account)
            await db.flush()
        profile = await db.scalar(select(Officer).where(Officer.account_id == account.id))
        if not profile:
            profile = Officer(
                account_id=account.id,
                name=name,
                badge_number=f"DEV-{role.value[:3]}-{account.id}",
                rank=name,
            )
            db.add(profile)
            await db.flush()
        if office_index is not None and offices:
            office = offices[office_index % len(offices)]
            member = await db.scalar(
                select(OfficeMembership.id).where(
                    OfficeMembership.officer_id == profile.id,
                    OfficeMembership.office_id == office.id,
                )
            )
            if not member:
                db.add(OfficeMembership(office_id=office.id, officer_id=profile.id))


def print_logins() -> None:
    print("Demo sign-ins:")
    for email, _name, role, _office in DEMO_STAFF:
        print(f"  {role.value:<13} {email} / {DEMO_PASSWORDS[role]}")
    print(f"  {'OFFICER':<13} officer1@example.com … officer4@example.com / OfficerPass!234")


async def seed() -> None:
    async with SessionLocal() as db:
        if await db.scalar(select(Account.id).limit(1)):
            offices = list((await db.scalars(select(Office).order_by(Office.id))).all())
            await ensure_demo_staff(db, offices)
            await db.commit()
            print("Database already contains data; demo staff updated.")
            print_logins()
            return
        offices = [
            Office(
                name="Governorpet Response Office",
                address="Governorpet, Vijayawada (development data)",
                latitude=16.5150,
                longitude=80.6300,
                service_radius=8,
            ),
            Office(
                name="Benz Circle Response Office",
                address="Benz Circle, Vijayawada (development data)",
                latitude=16.4985,
                longitude=80.6540,
                service_radius=8,
            ),
            Office(
                name="Gannavaram Response Office",
                address="Gannavaram (development data)",
                latitude=16.5400,
                longitude=80.8020,
                service_radius=15,
            ),
        ]
        db.add_all(offices)
        await db.flush()

        officer_accounts = [
            Account(
                email=f"officer{i}@example.com",
                password_hash=hash_password("OfficerPass!234"),
                role=Role.OFFICER,
            )
            for i in range(1, 5)
        ]
        user_accounts = [
            Account(
                email=f"user{i}@example.com",
                password_hash=hash_password("UserPass!234"),
                role=Role.USER,
            )
            for i in range(1, 3)
        ]
        db.add_all([*officer_accounts, *user_accounts])
        await db.flush()
        officers = [
            Officer(
                account_id=officer_accounts[i].id,
                name=f"Officer {i + 1}",
                badge_number=f"DEV-{101 + i}",
                rank="Response Officer",
            )
            for i in range(len(officer_accounts))
        ]
        users = [
            User(account_id=account.id, name=f"Development User {i + 1}")
            for i, account in enumerate(user_accounts)
        ]
        db.add_all([*officers, *users])
        await db.flush()
        db.add_all(
            [
                OfficeMembership(office_id=offices[i % 3].id, officer_id=officer.id)
                for i, officer in enumerate(officers)
            ]
        )

        now = datetime.now(UTC)
        reports = [
            Report(
                user_id=users[0].id,
                office_id=offices[1].id,
                assigned_officer_id=officers[1].id,
                category="Road Accident",
                description="Development-only previous collision report.",
                priority=Priority.HIGH,
                status=ReportStatus.RESOLVED,
                initial_latitude=16.5062,
                initial_longitude=80.6480,
                created_at=now - timedelta(days=7),
                resolved_at=now - timedelta(days=7, hours=-1),
            ),
            Report(
                user_id=users[1].id,
                office_id=offices[0].id,
                category="Public Safety Concern",
                description="Development-only report near the market.",
                priority=Priority.NORMAL,
                status=ReportStatus.NEW,
                initial_latitude=16.5120,
                initial_longitude=80.6310,
                created_at=now - timedelta(minutes=8),
            ),
            Report(
                user_id=users[0].id,
                office_id=offices[1].id,
                category="Medical Emergency",
                description="Person collapsed and needs urgent help.",
                priority=Priority.CRITICAL,
                status=ReportStatus.NEW,
                initial_latitude=16.5000,
                initial_longitude=80.6510,
                created_at=now - timedelta(minutes=2),
            ),
        ]
        db.add_all(reports)
        await db.flush()
        db.add_all(
            [
                ReportHistory(
                    report_id=report.id,
                    actor_type="USER",
                    actor_id=report.user_id,
                    event="REPORT_CREATED",
                    new_status=report.status.value,
                    event_metadata={},
                )
                for report in reports
            ]
        )
        await ensure_demo_staff(db, offices)
        await db.commit()
        print("Seed complete.")
        print_logins()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
