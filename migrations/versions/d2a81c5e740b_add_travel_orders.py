"""Add employee travel order requests.

Revision ID: d2a81c5e740b
Revises: c1d6f4a87b20
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa


revision = "d2a81c5e740b"
down_revision = "c1d6f4a87b20"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "travel_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("destination", sa.String(length=200), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("departure_date", sa.Date(), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="Pending",
            nullable=False,
        ),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approval_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_travel_orders_status_created",
        "travel_orders",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_travel_orders_employee_created",
        "travel_orders",
        ["employee_id", "created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_travel_orders_employee_created",
        table_name="travel_orders",
    )
    op.drop_index(
        "ix_travel_orders_status_created",
        table_name="travel_orders",
    )
    op.drop_table("travel_orders")
