"""Standardize stored department names to uppercase.

Revision ID: b84c7d91e206
Revises: f3c1a21b8d09
Create Date: 2026-11-01
"""
from alembic import op
import sqlalchemy as sa


revision = "b84c7d91e206"
down_revision = "f3c1a21b8d09"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text(
            """
            SELECT upper(trim(department_name)) AS normalized_name, count(*)
            FROM departments
            GROUP BY upper(trim(department_name))
            HAVING count(*) > 1
            """
        )
    ).all()
    if duplicates:
        duplicate_names = ", ".join(
            f"{name!r} ({count} rows)" for name, count in duplicates
        )
        raise RuntimeError(
            "Cannot uppercase department names because normalized duplicates "
            f"exist: {duplicate_names}. Resolve these departments before "
            "retrying the migration; no department data was changed."
        )

    connection.execute(
        sa.text(
            """
            UPDATE departments
            SET department_name = upper(trim(department_name))
            WHERE department_name <> upper(trim(department_name))
            """
        )
    )


def downgrade():
    # Original casing and whitespace cannot be reconstructed.
    pass
