"""Allow payslip requests for periods without payroll rows.

Revision ID: c1d6f4a87b20
Revises: b7c2f8a91d34
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa


revision = "c1d6f4a87b20"
down_revision = "b7c2f8a91d34"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "payslip_requests",
        sa.Column("pay_period_start", sa.Date(), nullable=True),
    )
    op.add_column(
        "payslip_requests",
        sa.Column("pay_period_end", sa.Date(), nullable=True),
    )
    op.execute(
        "UPDATE payslip_requests "
        "SET pay_period_start = ("
        "SELECT pay_period_start FROM payroll "
        "WHERE payroll.id = payslip_requests.payroll_id"
        "), pay_period_end = ("
        "SELECT pay_period_end FROM payroll "
        "WHERE payroll.id = payslip_requests.payroll_id"
        ")"
    )
    with op.batch_alter_table("payslip_requests") as batch_op:
        batch_op.alter_column(
            "pay_period_start",
            existing_type=sa.Date(),
            nullable=False,
        )
        batch_op.alter_column(
            "pay_period_end",
            existing_type=sa.Date(),
            nullable=False,
        )
        batch_op.alter_column(
            "payroll_id",
            existing_type=sa.Integer(),
            nullable=True,
        )

    op.drop_index(
        "uq_payslip_requests_pending_employee_payroll",
        table_name="payslip_requests",
    )
    op.create_index(
        "uq_payslip_requests_pending_employee_pay_period",
        "payslip_requests",
        ["employee_id", "pay_period_start", "pay_period_end"],
        unique=True,
        postgresql_where=sa.text("status = 'Pending'"),
        sqlite_where=sa.text("status = 'Pending'"),
    )


def downgrade():
    connection = op.get_bind()
    unlinked_requests = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM payslip_requests WHERE payroll_id IS NULL"
        )
    ).scalar_one()
    if unlinked_requests:
        raise RuntimeError(
            "Cannot downgrade while payslip requests exist without payroll records."
        )

    op.drop_index(
        "uq_payslip_requests_pending_employee_pay_period",
        table_name="payslip_requests",
    )
    with op.batch_alter_table("payslip_requests") as batch_op:
        batch_op.alter_column(
            "payroll_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.drop_column("pay_period_end")
        batch_op.drop_column("pay_period_start")

    op.create_index(
        "uq_payslip_requests_pending_employee_payroll",
        "payslip_requests",
        ["employee_id", "payroll_id"],
        unique=True,
        postgresql_where=sa.text("status = 'Pending'"),
        sqlite_where=sa.text("status = 'Pending'"),
    )
