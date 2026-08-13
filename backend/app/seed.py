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


async def seed() -> None:
    async with SessionLocal() as db:
        if await db.scalar(select(Account.id).limit(1)):
            print("Database already contains data; seed skipped.")
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

        admin_account = Account(
            email="admin@example.com",
            password_hash=hash_password("AdminPass!234"),
            role=Role.ADMIN,
        )
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
        db.add_all([admin_account, *officer_accounts, *user_accounts])
        await db.flush()
        officers = [
            Officer(
                account_id=officer_accounts[i].id,
                name=name,
                badge_number=f"DEV-{101 + i}",
                rank="Response Officer",
            )
            for i, name in enumerate(("Anita Rao", "Kumar Reddy", "Meera Das", "Arjun Singh"))
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
        await db.commit()
        print("Seed complete. Officer login: officer2@example.com / OfficerPass!234")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
