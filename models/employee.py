
from . import db
from sqlalchemy import String, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from decimal import Decimal


class Employee(db.Model):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )

    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False)
    position: Mapped[str] = mapped_column(String(100), nullable=False)
    salary: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Profile picture filename
    profile_picture: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    # Link to the Department
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id"), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="employee")
    department: Mapped["Department"] = relationship(back_populates="employees")

    leave_requests: Mapped[list["Leave"]] = relationship(
        back_populates="employee"
    )

    attendance_records: Mapped[list["Attendance"]] = relationship(
        back_populates="employee"
    )

    payroll_records: Mapped[list["Payroll"]] = relationship(
        back_populates="employee"
    )

    payslip_requests: Mapped[list["PayslipRequest"]] = relationship(
        back_populates="employee",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    travel_orders: Mapped[list["TravelOrder"]] = relationship(
        back_populates="employee",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    def __repr__(self):
        return f"<Employee {self.first_name} {self.last_name}>"
