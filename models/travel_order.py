from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from . import db


class TravelOrder(db.Model):
    __tablename__ = "travel_orders"
    __table_args__ = (
        Index("ix_travel_orders_status_created", "status", "created_at"),
        Index(
            "ix_travel_orders_employee_created",
            "employee_id",
            "created_at",
        ),
    )

    PENDING = "Pending"
    APPROVED = "Approved"
    DECLINED = "Declined"
    STATUSES = (PENDING, APPROVED, DECLINED)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    destination: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    departure_date: Mapped[date] = mapped_column(Date, nullable=False)
    return_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default=PENDING,
        server_default=PENDING,
        nullable=False,
    )
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approval_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    employee: Mapped["Employee"] = relationship(
        back_populates="travel_orders"
    )
    reviewer: Mapped["User | None"] = relationship(
        back_populates="reviewed_travel_orders",
        foreign_keys=[approved_by],
    )
