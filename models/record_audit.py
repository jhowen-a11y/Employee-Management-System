from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from . import db


class RecordAudit(db.Model):
    __tablename__ = "record_audit"
    __table_args__ = (
        Index(
            "ix_record_audit_record_created",
            "record_type",
            "record_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    before_values: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )
    after_values: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_username: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
