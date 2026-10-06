"""Staff roles: dispatcher, office admin, auditor.

``accounts.role`` is a non-native enum (a VARCHAR). It was sized for the
longest original value, ``OFFICER``; widen it so ``OFFICE_ADMIN`` fits on
databases that enforce VARCHAR length.

Revision ID: 0005_roles
Revises: 0004_stream_drafts
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_roles"
down_revision = "0004_stream_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.alter_column(
            "role",
            existing_type=sa.String(length=7),
            type_=sa.String(length=20),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Fold the new roles back onto the closest original one before narrowing.
    op.execute(
        "UPDATE accounts SET role = 'OFFICER' WHERE role IN ('DISPATCHER', 'OFFICE_ADMIN')"
    )
    op.execute("UPDATE accounts SET role = 'ADMIN' WHERE role = 'AUDITOR'")
    with op.batch_alter_table("accounts") as batch:
        batch.alter_column(
            "role",
            existing_type=sa.String(length=20),
            type_=sa.String(length=7),
            existing_nullable=False,
        )
