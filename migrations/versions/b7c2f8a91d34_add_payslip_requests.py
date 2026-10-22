"""Add employee payslip requests.

Revision ID: b7c2f8a91d34
Revises: 2c9d7f20c4ef
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa


revision = "b7c2f8a91d34"
down_revision = "2c9d7f20c4ef"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payslip_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("payroll_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="Pending",
            nullable=False,
        ),
        sa.Column("hr_remarks", sa.Text(), nullable=True),
        sa.Column(
            "request_date",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payroll_id"],
            ["payroll.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payslip_requests_status_date",
        "payslip_requests",
        ["status", "request_date"],
    )
    op.create_index(
        "uq_payslip_requests_pending_employee_payroll",
        "payslip_requests",
        ["employee_id", "payroll_id"],
        unique=True,
        postgresql_where=sa.text("status = 'Pending'"),
        sqlite_where=sa.text("status = 'Pending'"),
    )


def downgrade():
    op.drop_index(
        "uq_payslip_requests_pending_employee_payroll",
        table_name="payslip_requests",
    )
    op.drop_index(
        "ix_payslip_requests_status_date",
        table_name="payslip_requests",
    )
    op.drop_table("payslip_requests")
