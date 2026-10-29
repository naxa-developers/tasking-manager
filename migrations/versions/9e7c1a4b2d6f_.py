"""add rag chat tables

Revision ID: 9e7c1a4b2d6f
Revises: c3f8a1b2e9d4
Create Date: 2026-10-29 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "9e7c1a4b2d6f"
down_revision = "c3f8a1b2e9d4"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "rag_sessions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_sessions_updated_at", "rag_sessions", ["updated_at"], unique=False
    )
    op.create_index(
        op.f("ix_rag_sessions_user_id"), "rag_sessions", ["user_id"], unique=False
    )

    op.create_table(
        "rag_messages",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["rag_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_messages_session_created",
        "rag_messages",
        ["session_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "rag_rate_limits",
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column(
            "window_start",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )

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
        sa.Column("client_message_id", sa.String(length=64), nullable=True),
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
    op.create_index(
        "ix_rag_turns_client_message_id",
        "rag_turns",
        ["session_id", "client_message_id"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_rag_turns_client_message_id", table_name="rag_turns")
    op.drop_index("ix_rag_turns_session_created", table_name="rag_turns")
    op.drop_table("rag_turns")

    op.drop_table("rag_rate_limits")

    op.drop_index("ix_rag_messages_session_created", table_name="rag_messages")
    op.drop_table("rag_messages")

    op.drop_index(op.f("ix_rag_sessions_user_id"), table_name="rag_sessions")
    op.drop_index("ix_rag_sessions_updated_at", table_name="rag_sessions")
    op.drop_table("rag_sessions")
