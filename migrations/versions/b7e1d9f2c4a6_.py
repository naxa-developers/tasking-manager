"""add rag_rate_limits

Revision ID: b7e1d9f2c4a6
Revises: 6af8509cc74b
Create Date: 2026-09-28 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b7e1d9f2c4a6"
down_revision = "6af8509cc74b"
branch_labels = None
depends_on = None


def upgrade():
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


def downgrade():
    op.drop_table("rag_rate_limits")
