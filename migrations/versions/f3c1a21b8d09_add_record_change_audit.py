"""Add an append-only audit log for sensitive record changes.

Revision ID: f3c1a21b8d09
Revises: d2a81c5e740b
Create Date: 2026-11-01
"""
from alembic import op
import sqlalchemy as sa


revision = "f3c1a21b8d09"
down_revision = "d2a81c5e740b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "record_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_type", sa.String(length=30), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before_values", sa.JSON(), nullable=False),
        sa.Column("after_values", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_username", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_record_audit_record_created",
        "record_audit",
        ["record_type", "record_id", "created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_record_audit_record_created",
        table_name="record_audit",
    )
    op.drop_table("record_audit")
