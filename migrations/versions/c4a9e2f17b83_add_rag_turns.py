"""add rag_turns

Revision ID: c4a9e2f17b83
Revises: b7e1d9f2c4a6
Create Date: 2026-10-25 15:30:00.000000

One row per conversation turn: the question and its answer together. This is
the unit the API accepts and returns, so a session is a list of turns rather
than a stream of role-tagged messages.

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c4a9e2f17b83"
down_revision = "b7e1d9f2c4a6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rag_turns",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("route", sa.String(length=16), nullable=True),
        sa.Column("ops", postgresql.JSONB(), nullable=True),
        sa.Column("project_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("citations", postgresql.JSONB(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["rag_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_turns_session_created",
        "rag_turns",
        ["session_id", "created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_rag_turns_session_created", table_name="rag_turns")
    op.drop_table("rag_turns")
