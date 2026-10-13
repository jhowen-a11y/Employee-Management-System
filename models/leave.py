
from . import db
from sqlalchemy import String, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import date, datetime


class Leave(db.Model):
    __tablename__ = "leaves"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Connect to Employee
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)

    leave_type: Mapped[str] = mapped_column(String(50),nullable=False)

    start_date: Mapped[date] = mapped_column(Date,nullable=False)

    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="Pending",nullable=False)

    created_at: Mapped[datetime] = mapped_column( DateTime(timezone=True),server_default=func.now())

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now())

    # Relationship to Employee
    employee: Mapped["Employee"] = relationship(back_populates="leave_requests") # san galing tong leave_requests

    def __repr__(self):
        return (
            f"<Leave Employee ID: {self.employee_id}, "
            f"Type: {self.leave_type}, Status: {self.status}>"
        )
