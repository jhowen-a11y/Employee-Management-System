"""Persist database backup metadata.

Revision ID: 91d2a7c4f630
Revises: f3c1a21b8d09, e7c4a91d2b63
Create Date: 2026-11-05
"""
from alembic import op
import sqlalchemy as sa


revision = "91d2a7c4f630"
down_revision = "e7c4a91d2b63"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "database_backups",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("encrypted", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_database_backups_created_at",
        "database_backups",
        ["created_at"],
    )
    op.create_table(
        "database_backup_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("backup_id", sa.String(length=32), nullable=True),
        sa.Column("destination_database", sa.String(length=63), nullable=True),
        sa.Column("message", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_database_backup_jobs_created_at",
        "database_backup_jobs",
        ["created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_database_backup_jobs_created_at",
        table_name="database_backup_jobs",
    )
    op.drop_table("database_backup_jobs")
    op.drop_index(
        "ix_database_backups_created_at",
        table_name="database_backups",
    )
    op.drop_table("database_backups")
