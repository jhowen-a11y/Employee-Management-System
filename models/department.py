from . import db
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime


class Department(db.Model):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_name: Mapped[str] = mapped_column(String(100),unique=True,nullable=False)
    description: Mapped[str | None] = mapped_column(String(255),nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now())

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now())

    employees: Mapped[list["Employees"]] = relationship(
        back_populates="department"
    )

    def __repr__(self):
        return f"<Department {self.department_name}>"