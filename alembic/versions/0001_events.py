"""create events table

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("agent_version", sa.String(128), nullable=False),
        sa.Column("prompt_hash", sa.String(128), nullable=True),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("outcome_labels", sa.JSON, nullable=True),
        sa.UniqueConstraint("run_id", "seq", name="uq_events_run_seq"),
    )
    op.create_index("ix_events_run_id", "events", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_events_run_id", table_name="events")
    op.drop_table("events")
