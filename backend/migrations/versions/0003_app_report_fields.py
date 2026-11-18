"""Add the fields the Equal mobile app files a report with.

The app writes the whole report on the device — a title, a severity, a
situation analysis, the recommended actions, and the signed transcript the
analysis was written from. `reports.description` alone would keep the summary
and discard the rest, which is the part a responder most needs.

Every column is nullable: reports filed through the existing mobile endpoint
have none of them, and nothing already stored is rewritten.

Revision ID: 0003_app_report_fields
Revises: 0002_stream_recording
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_app_report_fields"
down_revision = "0002_stream_recording"
branch_labels = None
depends_on = None

COLUMNS = (
    sa.Column("reference_code", sa.String(length=20), nullable=True),
    sa.Column("client_id", sa.String(length=64), nullable=True),
    sa.Column("title", sa.String(length=300), nullable=True),
    sa.Column("severity", sa.String(length=20), nullable=True),
    sa.Column("situation_analysis", sa.Text(), nullable=True),
    sa.Column("recommended_actions", sa.JSON(), nullable=True),
    sa.Column("transcript", sa.Text(), nullable=True),
    sa.Column("labels", sa.JSON(), nullable=True),
    sa.Column("duration_ms", sa.Integer(), nullable=True),
    sa.Column("location_label", sa.String(length=300), nullable=True),
    sa.Column("reporter_name", sa.String(length=120), nullable=True),
    sa.Column("source", sa.String(length=20), nullable=True),
    sa.Column("generated_by", sa.String(length=60), nullable=True),
)


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("reports")}
    for column in COLUMNS:
        if column.name not in existing:
            op.add_column("reports", column.copy())
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("reports")}
    if "ix_reports_reference_code" not in indexes:
        op.create_index("ix_reports_reference_code", "reports", ["reference_code"], unique=True)
    if "ix_reports_client_id" not in indexes:
        op.create_index("ix_reports_client_id", "reports", ["client_id"])


def downgrade() -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("reports")}
    if "ix_reports_client_id" in indexes:
        op.drop_index("ix_reports_client_id", table_name="reports")
    if "ix_reports_reference_code" in indexes:
        op.drop_index("ix_reports_reference_code", table_name="reports")
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("reports")}
    for column in reversed(COLUMNS):
        if column.name in existing:
            op.drop_column("reports", column.name)
