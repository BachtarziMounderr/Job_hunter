"""Preserve partial-description evidence and daily execution history."""

import sqlalchemy as sa

from alembic import op

revision = "a17300000001"
down_revision = "46d52abc38ae"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(
            sa.Column(
                "description_complete", sa.Boolean(), nullable=False, server_default=sa.true()
            )
        )
    op.create_table(
        "daily_search_runs",
        sa.Column("run_key", sa.String(100), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("report_message_id", sa.String(100)),
    )


def downgrade():
    op.drop_table("daily_search_runs")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("description_complete")
