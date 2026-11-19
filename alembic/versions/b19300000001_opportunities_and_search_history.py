"""Durable opportunity identity, application status and daily search history."""

import sqlalchemy as sa

from alembic import op

revision = "b19300000001"
down_revision = "a17300000001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity_key", sa.String(64), nullable=False, unique=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("notification_status", sa.String(20), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('available', 'applied', 'dismissed')", name="status"),
        sa.CheckConstraint(
            "notification_status IN ('pending', 'sending', 'sent', 'uncertain')",
            name="notification_status",
        ),
    )
    op.create_index(
        "ix_opportunities_status_discovered", "opportunities", ["status", "discovered_at"]
    )
    op.create_table(
        "search_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("details", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("search_executions")
    op.drop_index("ix_opportunities_status_discovered", table_name="opportunities")
    op.drop_table("opportunities")
