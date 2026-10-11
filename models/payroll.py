
from . import db
from sqlalchemy import Date, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import date, datetime
from decimal import Decimal


class Payroll(db.Model):
    __tablename__ = "payroll"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Connect to Employee
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"),nullable=False)

    pay_period_start: Mapped[date] = mapped_column(Date,nullable=False)

    pay_period_end: Mapped[date] = mapped_column(Date,nullable=False)

    basic_salary: Mapped[Decimal] = mapped_column(Numeric(10, 2),nullable=False)

    allowances: Mapped[Decimal] = mapped_column(Numeric(10, 2),default=Decimal("0.00"),nullable=False)

    deductions: Mapped[Decimal] = mapped_column(Numeric(10, 2),default=Decimal("0.00"),nullable=False)

    net_pay: Mapped[Decimal] = mapped_column(Numeric(10, 2),nullable=False)

    payment_date: Mapped[date | None] = mapped_column(Date,nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now())

    # Relationship to Employee
    employee: Mapped["Employee"] = relationship(
        back_populates="payroll_records"
    )

    def __repr__(self):
        return (
            f"<Payroll Employee ID: {self.employee_id}, "
            f"Net Pay: {self.net_pay}>"
        )
