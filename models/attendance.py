from . import db
from sqlalchemy import Date, Time, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import date, time, datetime


class Attendance(db.Model):
    __tablename__ = "attendance"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Connect attendance to an employee
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"),nullable=False)

    attendance_date: Mapped[date] = mapped_column(Date,nullable=False)
    

    time_in: Mapped[time | None] = mapped_column(Time, nullable=True)

    time_out: Mapped[time | None] = mapped_column(Time,nullable=True)

    status: Mapped[str] = mapped_column(String(20),default="Present",nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now())

    # Connect to the Employee model
    employee: Mapped["Employee"] = relationship(back_populates="attendance_records", lazy= "selectin")

    def __repr__(self):
        return (
            f"<Attendance Employee ID: {self.employee_id}, "
            f"Date: {self.attendance_date}, Status: {self.status}>"
        )
