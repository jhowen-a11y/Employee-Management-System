"""Standalone proof-of-concept script for GitHub Actions database backup.

This script is intentionally self-contained and safe for CI use:

- Sets temporary environment variables BEFORE importing app.py.
- Uses a disposable PostgreSQL 17 service container database.
- Uses local backup storage (no Supabase, no production credentials).
- Verifies the generated backup package and metadata.
- Prints only safe, non-sensitive information.
- Exits with code 0 on success, nonzero on failure.
"""

import os
import sys
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Set temporary environment variables BEFORE importing app.py.
# These values are clearly labeled non-production test values.
# ---------------------------------------------------------------------------
os.environ["SECRET_KEY"] = "poc-test-secret-key-not-production"
os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/ems_poc_test"

# ---------------------------------------------------------------------------
# Import application factory and backup functions.
# Importing app.py triggers app.create_app() at module level (app.py:519),
# which reads the environment variables set above.
# ---------------------------------------------------------------------------
from app import create_app  # noqa: E402  (intentional after env setup)
from services.database_backups import (  # noqa: E402
    create_backup,
    list_backups,
)


BACKUP_DIRECTORY = "/tmp/ems-poc-backups"


def _verify_backup_package(backup_directory: Path) -> None:
    """Verify the generated backup package and metadata files."""
    backup_files = list(backup_directory.glob("*.emsbackup"))
    metadata_files = list(backup_directory.glob("*.json"))

    if len(backup_files) < 1:
        raise RuntimeError("No .emsbackup file found in backup directory")
    if len(metadata_files) < 1:
        raise RuntimeError("No JSON metadata file found in backup directory")

    package_path = backup_files[0]
    metadata_path = metadata_files[0]

    # Verify the backup package is a valid ZIP archive.
    if not zipfile.is_zipfile(package_path):
        raise RuntimeError("Backup package is not a valid ZIP archive")

    with zipfile.ZipFile(package_path) as archive:
        names = archive.namelist()
        if "manifest.json" not in names:
            raise RuntimeError("Backup package is missing manifest.json")
        if "backup.dump" not in names:
            raise RuntimeError("Backup package is missing backup.dump")

        import json
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != "mcm-ems-postgresql":
            raise RuntimeError(
                f"Unexpected manifest format: {manifest.get('format')}"
            )
        if manifest.get("version") != 1:
            raise RuntimeError(
                f"Unexpected manifest version: {manifest.get('version')}"
            )

    # Verify metadata file content.
    import json
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "successful":
        raise RuntimeError(
            f"Backup metadata status is not successful: {metadata.get('status')}"
        )
    if metadata.get("created_by") != "github-actions-poc":
        raise RuntimeError(
            f"Unexpected created_by: {metadata.get('created_by')}"
        )
    if not isinstance(metadata.get("file_size"), int) or metadata["file_size"] <= 0:
        raise RuntimeError(
            f"Unexpected file_size: {metadata.get('file_size')}"
        )


def main() -> None:
    """Run the backup proof-of-concept."""
    # Create the backup directory.
    backup_dir = Path(BACKUP_DIRECTORY)
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    # Create the Flask application with TESTING=True.
    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": os.environ["DATABASE_URL"],
            "SECRET_KEY": os.environ["SECRET_KEY"],
            "TESTING": True,
        }
    )
    # Explicitly select local backup storage (no Supabase).
    app.config["BACKUP_STORAGE_BACKEND"] = "local"
    app.config["BACKUP_DIRECTORY"] = BACKUP_DIRECTORY

    with app.app_context():
        # Run the existing backup function.
        backup = create_backup("github-actions-poc")

        if backup.get("status") != "successful":
            print(
                f"ERROR: Backup failed with status: {backup.get('status')}",
                file=sys.stderr,
            )
            sys.exit(1)

        # Verify the backup can be listed.
        backups = list_backups(limit=5)
        if len(backups) < 1:
            print("ERROR: No backups found in list_backups()", file=sys.stderr)
            sys.exit(1)

        listed = backups[0]
        if listed.get("id") != backup.get("id"):
            print(
                "ERROR: Listed backup ID does not match created backup ID",
                file=sys.stderr,
            )
            sys.exit(1)

    # Verify the generated package and metadata files.
    _verify_backup_package(backup_dir)

    # Print only safe, non-sensitive information.
    print(f"SUCCESS: Backup {backup['id']} created and verified.")
    print(f"SUCCESS: Backup listed successfully ({len(backups)} total).")
    print(f"SUCCESS: Backup package and metadata validated.")
    sys.exit(0)


if __name__ == "__main__":
    main()