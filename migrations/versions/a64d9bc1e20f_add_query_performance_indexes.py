"""Add indexes for frequent list and dashboard queries.

Revision ID: a64d9bc1e20f
Revises: 093f324b2ba1
Create Date: 2026-10-19
"""
from alembic import op


revision = "a64d9bc1e20f"
down_revision = "093f324b2ba1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_attendance_date_id",
        "attendance",
        ["attendance_date", "id"],
    )
    op.create_index(
        "ix_attendance_employee_date_id",
        "attendance",
        ["employee_id", "attendance_date", "id"],
    )
    op.create_index(
        "ix_attendance_date_status",
        "attendance",
        ["attendance_date", "status"],
    )
    op.create_index(
        "ix_leaves_created_id",
        "leaves",
        ["created_at", "id"],
    )
    op.create_index(
        "ix_leaves_employee_created_id",
        "leaves",
        ["employee_id", "created_at", "id"],
    )
    op.create_index("ix_leaves_status", "leaves", ["status"])
    op.create_index(
        "ix_payroll_period_id",
        "payroll",
        ["pay_period_start", "id"],
    )
    op.create_index(
        "ix_payroll_employee_period_id",
        "payroll",
        ["employee_id", "pay_period_start", "id"],
    )


def downgrade():
    op.drop_index("ix_payroll_employee_period_id", table_name="payroll")
    op.drop_index("ix_payroll_period_id", table_name="payroll")
    op.drop_index("ix_leaves_status", table_name="leaves")
    op.drop_index("ix_leaves_employee_created_id", table_name="leaves")
    op.drop_index("ix_leaves_created_id", table_name="leaves")
    op.drop_index("ix_attendance_date_status", table_name="attendance")
    op.drop_index("ix_attendance_employee_date_id", table_name="attendance")
    op.drop_index("ix_attendance_date_id", table_name="attendance")
