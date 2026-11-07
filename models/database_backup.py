from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.sql import func

from models import db


class DatabaseBackup(db.Model):
    __tablename__ = "database_backups"

    id = db.Column(String(32), primary_key=True)
    filename = db.Column(String(255), nullable=False)
    created_at = db.Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    file_size = db.Column(Integer, nullable=False, default=0)
    created_by = db.Column(String(100), nullable=False)
    encrypted = db.Column(Boolean, nullable=False, default=False)
    status = db.Column(String(20), nullable=False)
    storage_key = db.Column(String(255), nullable=True)
    verified = db.Column(Boolean, nullable=False, default=False)


class DatabaseBackupJob(db.Model):
    __tablename__ = "database_backup_jobs"

    id = db.Column(String(32), primary_key=True)
    operation = db.Column(String(20), nullable=False)
    status = db.Column(String(20), nullable=False)
    created_at = db.Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    updated_at = db.Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by = db.Column(String(100), nullable=False)
    backup_id = db.Column(String(32), nullable=True)
    destination_database = db.Column(String(63), nullable=True)
    message = db.Column(String(255), nullable=True)
