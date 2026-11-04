"""Store automatic attendance deductions with payroll history.

Revision ID: d34e5f6a7b89
Revises: b84c7d91e206
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa


revision = "d34e5f6a7b89"
down_revision = "b84c7d91e206"
branch_labels = None
depends_on = None


def upgrade():
    duplicate = op.get_bind().execute(
        sa.text(
            """
            SELECT employee_id, pay_period_start, pay_period_end
            FROM payroll
            GROUP BY employee_id, pay_period_start, pay_period_end
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate:
        raise RuntimeError(
            "Cannot enforce unique payroll periods while duplicate employee "
            "pay-period records exist. Resolve duplicates without deleting "
            "payroll history, then rerun the migration."
        )

    op.add_column(
        "payroll",
        sa.Column("absence_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "payroll",
        sa.Column("late_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "payroll",
        sa.Column("absence_deduction", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "payroll",
        sa.Column("late_deduction", sa.Numeric(10, 2), nullable=True),
    )
    op.create_unique_constraint(
        "uq_payroll_employee_period",
        "payroll",
        ["employee_id", "pay_period_start", "pay_period_end"],
    )


def downgrade():
    op.drop_constraint(
        "uq_payroll_employee_period",
        "payroll",
        type_="unique",
    )
    op.drop_column("payroll", "late_deduction")
    op.drop_column("payroll", "absence_deduction")
    op.drop_column("payroll", "late_minutes")
    op.drop_column("payroll", "absence_days")
