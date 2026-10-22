from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from . import db


class PayslipRequest(db.Model):
    __tablename__ = "payslip_requests"
    __table_args__ = (
        Index("ix_payslip_requests_status_date", "status", "request_date"),
        Index(
            "uq_payslip_requests_pending_employee_pay_period",
            "employee_id",
            "pay_period_start",
            "pay_period_end",
            unique=True,
            postgresql_where=text("status = 'Pending'"),
            sqlite_where=text("status = 'Pending'"),
        ),
    )

    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    STATUSES = (PENDING, APPROVED, REJECTED)
    REASONS = (
        "Personal copy",
        "Loan or financial requirement",
        "Payslip not received",
        "Other",
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    payroll_id: Mapped[int | None] = mapped_column(
        ForeignKey("payroll.id", ondelete="CASCADE"),
        nullable=True,
    )
    pay_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    pay_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default=PENDING,
        server_default=PENDING,
        nullable=False,
    )
    hr_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    employee: Mapped["Employee"] = relationship(
        back_populates="payslip_requests"
    )
    payroll: Mapped["Payroll | None"] = relationship(
        back_populates="payslip_requests"
    )
    reviewer: Mapped["User | None"] = relationship(
        back_populates="reviewed_payslip_requests",
        foreign_keys=[reviewed_by],
    )
