from . import db
from flask_login import UserMixin
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime, timezone


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    ADMIN = "admin"
    EMPLOYEE = "employee"
    HR = "hr"
    ROLES = (ADMIN, HR, EMPLOYEE)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=EMPLOYEE)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    employee: Mapped["Employee | None"] = relationship(
        back_populates="user"
    )

    def __repr__(self):
        return f"<User {self.username} (Role: {self.role})>"