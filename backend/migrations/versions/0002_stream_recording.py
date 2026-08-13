"""Add saved live-video recording fields.

Revision ID: 0002_stream_recording
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_stream_recording"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("stream_sessions")}
    if "egress_id" not in columns:
        op.add_column(
            "stream_sessions", sa.Column("egress_id", sa.String(length=120), nullable=True)
        )
    if "recording_key" not in columns:
        op.add_column(
            "stream_sessions", sa.Column("recording_key", sa.String(length=500), nullable=True)
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("stream_sessions")}
    if "recording_key" in columns:
        op.drop_column("stream_sessions", "recording_key")
    if "egress_id" in columns:
        op.drop_column("stream_sessions", "egress_id")
