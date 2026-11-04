"""Snapshot the number of late occurrences with payroll deductions.

Revision ID: e7c4a91d2b63
Revises: d34e5f6a7b89
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa


revision = "e7c4a91d2b63"
down_revision = "d34e5f6a7b89"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "payroll",
        sa.Column("late_occurrences", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column("payroll", "late_occurrences")
