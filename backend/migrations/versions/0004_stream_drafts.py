"""Unauthenticated /app live-stream transcripts.

The streaming endpoints take no login (like ``POST /app/api/v1/predict``), so
the accumulated transcript cannot key on a user. One row per stream, addressed
by an opaque stream id plus a secret whose SHA-256 is stored; the phone uses
``GET /app/api/v1/stream/{stream_id}/draft?token=`` to prefill its report.

Revision ID: 0004_stream_drafts
Revises: 0003_app_report_fields
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_stream_drafts"
down_revision = "0003_app_report_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001_initial runs Base.metadata.create_all, so a fresh database already
    # has this table; only backfill databases created before this revision.
    existing_tables = sa.inspect(op.get_bind()).get_table_names()
    if "stream_drafts" not in existing_tables:
        op.create_table(
            "stream_drafts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("stream_id", sa.String(length=32), nullable=False),
            sa.Column("secret_hash", sa.String(length=128), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="landmarks"),
            sa.Column("transcript", sa.Text(), nullable=False, server_default=""),
            sa.Column("sentences", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("safety_events", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("frames_seen", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("stream_drafts")}
    if "ix_stream_drafts_stream_id" not in indexes:
        op.create_index("ix_stream_drafts_stream_id", "stream_drafts", ["stream_id"], unique=True)
    if "ix_stream_drafts_created_at" not in indexes:
        op.create_index("ix_stream_drafts_created_at", "stream_drafts", ["created_at"])
    if "ix_stream_drafts_expires_at" not in indexes:
        op.create_index("ix_stream_drafts_expires_at", "stream_drafts", ["expires_at"])


def downgrade() -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("stream_drafts")}
    for name in (
        "ix_stream_drafts_expires_at",
        "ix_stream_drafts_created_at",
        "ix_stream_drafts_stream_id",
    ):
        if name in indexes:
            op.drop_index(name, table_name="stream_drafts")
    if "stream_drafts" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("stream_drafts")
