import sqlalchemy as sa
from alembic import op

revision = "0006_maps_location_fields"
down_revision = "0005_roles"
branch_labels = None
depends_on = None

REPORT_COLUMNS = (
    sa.Column("formatted_address", sa.String(length=500), nullable=True),
    sa.Column("plus_code", sa.String(length=32), nullable=True),
    sa.Column("eta_seconds", sa.Integer(), nullable=True),
    sa.Column("route_source", sa.String(length=20), nullable=True),
)
PLACE_INDEX = "ix_offices_google_place_id"


def columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    existing = columns("reports")
    for column in REPORT_COLUMNS:
        if column.name not in existing:
            op.add_column("reports", column.copy())
    if "google_place_id" not in columns("offices"):
        op.add_column("offices", sa.Column("google_place_id", sa.String(length=255), nullable=True))
    if PLACE_INDEX not in indexes("offices"):
        op.create_index(PLACE_INDEX, "offices", ["google_place_id"], unique=True)


def downgrade() -> None:
    if PLACE_INDEX in indexes("offices"):
        op.drop_index(PLACE_INDEX, table_name="offices")
    if "google_place_id" in columns("offices"):
        with op.batch_alter_table("offices") as batch:
            batch.drop_column("google_place_id")
    existing = columns("reports")
    with op.batch_alter_table("reports") as batch:
        for column in reversed(REPORT_COLUMNS):
            if column.name in existing:
                batch.drop_column(column.name)
