"""add client_message_id to rag_turns

Revision ID: 9e7c1a4b2d6f
Revises: c4a9e2f17b83
Create Date: 2026-10-28 11:45:00.000000

Idempotency key for a client retry of the same turn. Nullable so existing rows
and clients that do not send a key keep working.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9e7c1a4b2d6f"
down_revision = "c4a9e2f17b83"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "rag_turns",
        sa.Column("client_message_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_rag_turns_client_message_id",
        "rag_turns",
        ["session_id", "client_message_id"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_rag_turns_client_message_id", table_name="rag_turns")
    op.drop_column("rag_turns", "client_message_id")
