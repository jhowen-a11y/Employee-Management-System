import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from flask import current_app
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename

from models import db
from models.database_backup import DatabaseBackup
from services.supabase_storage import (
    SupabaseStorageConfigurationError,
    storage_bucket,
)


logger = logging.getLogger(__name__)
FORMAT_VERSION = 1
MAX_BACKUP_SIZE = 512 * 1024 * 1024
MAX_MANIFEST_SIZE = 16 * 1024
MAX_PACKAGE_SIZE = MAX_BACKUP_SIZE + MAX_MANIFEST_SIZE + 1024 * 1024
MAX_REMOTE_PACKAGE_SIZE = 50 * 1000 * 1000
BACKUP_BUCKET = "ems-database-backups"
BACKUP_STORAGE_PREFIX = "ems"
MAX_HISTORY_ITEMS = 200
PBKDF2_ITERATIONS = 600_000
PASSWORD_MIN_LENGTH = 12
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
BACKUP_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
LOCAL_OPERATION_LOCK = threading.Lock()
PACKAGE_EXTENSION = ".emsbackup"


class BackupError(Exception):
    def __init__(self, public_message):
        super().__init__(public_message)
        self.public_message = public_message


def _backup_directory():
    configured = current_app.config.get("BACKUP_DIRECTORY") or os.getenv(
        "EMS_BACKUP_DIRECTORY"
    )
    if configured:
        directory = Path(configured).expanduser()
    elif os.name == "nt":
        local_data = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        directory = local_data / "MCM-EMS" / "database-backups"
    else:
        local_data = Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        directory = local_data / "mcm-ems" / "database-backups"
    directory = directory.resolve()
    static_directory = Path(current_app.static_folder).resolve()
    if directory == static_directory or static_directory in directory.parents:
        raise BackupError("Private backup storage must be outside the public files directory.")
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            directory.chmod(0o700)
    except OSError as error:
        logger.error("Could not prepare private backup storage: error_type=%s", type(error).__name__)
        raise BackupError("Private backup storage is unavailable.") from error
    return directory


def _uses_supabase_storage():
    return current_app.config.get("BACKUP_STORAGE_BACKEND", "local") == "supabase"


def _package_size_limit():
    return MAX_REMOTE_PACKAGE_SIZE if _uses_supabase_storage() else MAX_PACKAGE_SIZE


def _package_size_error():
    if _uses_supabase_storage():
        return "The final backup package exceeds the 50 MB Supabase Storage limit."
    return "The generated backup exceeds the 512 MB size limit."


def _backup_storage_bucket():
    try:
        return storage_bucket(BACKUP_BUCKET)
    except SupabaseStorageConfigurationError as error:
        logger.error("Supabase backup storage is unavailable: error_type=%s", type(error).__name__)
        raise BackupError("Private backup storage is unavailable.") from error


def _storage_key(backup_id):
    if not BACKUP_ID_PATTERN.fullmatch(backup_id):
        raise BackupError("The requested backup is invalid.")
    return f"{BACKUP_STORAGE_PREFIX}/{backup_id}{PACKAGE_EXTENSION}"


def _upload_package(path, storage_key):
    try:
        bucket = _backup_storage_bucket()
        with path.open("rb") as package:
            bucket.upload(
                storage_key,
                package.read(),
                {
                    "content-type": "application/zip",
                    "upsert": "false",
                },
            )
    except BackupError:
        raise
    except Exception as error:
        logger.error("Could not upload backup object: error_type=%s", type(error).__name__)
        raise BackupError("The backup could not be saved to private storage.") from error


def _download_package(storage_key):
    try:
        contents = _backup_storage_bucket().download(storage_key)
    except BackupError:
        raise
    except Exception as error:
        logger.error("Could not retrieve backup object: error_type=%s", type(error).__name__)
        raise BackupError("The selected backup could not be retrieved from private storage.") from error
    if not isinstance(contents, bytes) or len(contents) > MAX_REMOTE_PACKAGE_SIZE:
        raise BackupError("The selected backup file is invalid or exceeds 50 MB.")
    return contents


def _delete_package(storage_key):
    try:
        _backup_storage_bucket().remove([storage_key])
    except BackupError:
        raise
    except Exception as error:
        logger.error("Could not delete backup object: error_type=%s", type(error).__name__)
        raise BackupError("The backup could not be deleted from private storage.") from error


def _database_url():
    url = db.engine.url
    if url.get_backend_name() != "postgresql":
        raise BackupError("Database backup and restore require PostgreSQL.")
    return url


def _utility_path(name):
    configured = current_app.config.get(
        "PG_DUMP_PATH" if name == "pg_dump" else "PG_RESTORE_PATH"
    ) or os.getenv("PG_DUMP_PATH" if name == "pg_dump" else "PG_RESTORE_PATH")
    utility = None
    if configured:
        configured_path = Path(configured).expanduser()
        utility = (
            str(configured_path)
            if configured_path.is_file()
            else shutil.which(configured)
        )
    else:
        utility = shutil.which(name)
    if not utility or not Path(utility).is_file():
        raise BackupError(
            "PostgreSQL backup utilities are unavailable on this server."
        )
    return str(Path(utility).resolve())


def _tool_environment(url):
    environment = os.environ.copy()
    environment.pop("PGPASSWORD", None)
    for key, value in (
        ("PGHOST", url.host),
        ("PGPORT", str(url.port) if url.port else None),
        ("PGUSER", url.username),
        ("PGDATABASE", url.database),
    ):
        environment.pop(key, None)
        if value is not None:
            environment[key] = value
    for query_key, environment_key in (
        ("sslmode", "PGSSLMODE"),
        ("sslrootcert", "PGSSLROOTCERT"),
        ("sslcert", "PGSSLCERT"),
        ("sslkey", "PGSSLKEY"),
    ):
        value = url.query.get(query_key)
        if value:
            environment[environment_key] = str(value)
    passfile = None
    if url.password is not None:
        if "\n" in url.password or "\r" in url.password:
            raise BackupError("Unable to use the configured PostgreSQL credentials.")
        environment.pop("PGPASSFILE", None)

        def escape_passfile_field(value):
            return str(value).replace("\\", "\\\\").replace(":", "\\:")

        fields = (
            url.host or "*",
            str(url.port) if url.port else "*",
            url.database or "*",
            url.username or "*",
            url.password,
        )
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                prefix="ems-pgpass-",
            ) as file:
                passfile = Path(file.name)
                file.write(":".join(escape_passfile_field(field) for field in fields))
                file.write("\n")
            if os.name != "nt":
                passfile.chmod(0o600)
            environment["PGPASSFILE"] = str(passfile)
        except OSError as error:
            if passfile:
                passfile.unlink(missing_ok=True)
            logger.error("Could not prepare PostgreSQL credentials: error_type=%s", type(error).__name__)
            raise BackupError("Unable to complete the database operation. Please try again.") from error
    return environment, passfile


def _run_tool(arguments, url, timeout=900):
    passfile = None
    try:
        environment, passfile = _tool_environment(url)
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.error("PostgreSQL backup utility failed: error_type=%s", type(error).__name__)
        raise BackupError("Unable to complete the database operation. Please try again.") from error
    finally:
        if passfile:
            try:
                passfile.unlink(missing_ok=True)
            except OSError as error:
                logger.error(
                    "Could not remove temporary PostgreSQL credentials: error_type=%s",
                    type(error).__name__,
                )
                raise BackupError(
                    "Unable to complete the database operation. Please try again."
                ) from error
    if result.returncode:
        stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
        logger.error(
            "PostgreSQL backup utility returned an error: return_code=%s stderr=%s",
            result.returncode,
            stderr_text,
        )
        raise BackupError("Unable to complete the database operation. Please try again.")
    return result


def _password_key(password, salt):
    if len(password) < PASSWORD_MIN_LENGTH:
        raise BackupError("Use an encryption password with at least 12 characters.")
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    ).derive(password.encode("utf-8"))


def _encrypt_file(source, destination, password, salt, nonce):
    encryptor = Cipher(
        algorithms.AES(_password_key(password, salt)),
        modes.GCM(nonce),
    ).encryptor()
    with source.open("rb") as input_file, destination.open("wb") as output_file:
        while chunk := input_file.read(1024 * 1024):
            output_file.write(encryptor.update(chunk))
        output_file.write(encryptor.finalize())
        output_file.write(encryptor.tag)


def _decrypt_file(source, destination, password, salt, nonce):
    size = source.stat().st_size
    if size < 16:
        raise BackupError("The uploaded backup file is invalid.")
    with source.open("rb") as input_file:
        input_file.seek(-16, os.SEEK_END)
        tag = input_file.read(16)
        input_file.seek(0)
        decryptor = Cipher(
            algorithms.AES(_password_key(password, salt)),
            modes.GCM(nonce, tag),
        ).decryptor()
        remaining = size - 16
        try:
            with destination.open("wb") as output_file:
                while remaining:
                    chunk = input_file.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise BackupError("The uploaded backup file is invalid.")
                    remaining -= len(chunk)
                    output_file.write(decryptor.update(chunk))
                output_file.write(decryptor.finalize())
        except Exception:
            destination.unlink(missing_ok=True)
            raise


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _manifest_signature(manifest):
    signing_key = current_app.config["SECRET_KEY"]
    if isinstance(signing_key, str):
        signing_key = signing_key.encode("utf-8")
    unsigned_manifest = {
        key: value for key, value in manifest.items() if key != "signature"
    }
    return hmac.new(
        signing_key,
        _canonical_json(unsigned_manifest),
        hashlib.sha256,
    ).hexdigest()


def _digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as backup_file:
        for chunk in iter(lambda: backup_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_package(dump_path, package_path, password):
    payload_path = dump_path
    manifest = {
        "format": "mcm-ems-postgresql",
        "version": FORMAT_VERSION,
        "encrypted": bool(password),
    }
    if password:
        salt = os.urandom(16)
        nonce = os.urandom(12)
        payload_path = dump_path.with_suffix(".encrypted")
        _encrypt_file(dump_path, payload_path, password, salt, nonce)
        manifest.update(
            {
                "salt": salt.hex(),
                "nonce": nonce.hex(),
                "iterations": PBKDF2_ITERATIONS,
            }
        )
    manifest["payload_size"] = payload_path.stat().st_size
    if manifest["payload_size"] > MAX_BACKUP_SIZE:
        raise BackupError("The database dump exceeds the 50 MB storage limit.")
    manifest["payload_sha256"] = _digest_file(payload_path)
    manifest["signature"] = _manifest_signature(manifest)
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_STORED) as package:
        package.writestr(
            "manifest.json",
            _canonical_json(manifest),
        )
        package.write(payload_path, "backup.enc" if password else "backup.dump")
    if package_path.stat().st_size > _package_size_limit():
        raise BackupError(_package_size_error())


def _read_manifest(package):
    try:
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            if (
                len(names) != 2
                or len(set(names)) != 2
                or "manifest.json" not in names
            ):
                raise BackupError("The uploaded backup file is invalid.")
            manifest_info = archive.getinfo("manifest.json")
            if manifest_info.file_size > MAX_MANIFEST_SIZE:
                raise BackupError("The uploaded backup file is invalid.")
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict):
                raise BackupError("The uploaded backup file is invalid.")
            encrypted = manifest.get("encrypted")
            expected_payload = "backup.enc" if encrypted is True else "backup.dump"
            if archive.namelist().count(expected_payload) != 1:
                raise BackupError("The uploaded backup file is invalid.")
            payload_info = archive.getinfo(expected_payload)
            expected_keys = {
                "format",
                "version",
                "encrypted",
                "payload_size",
                "payload_sha256",
                "signature",
            }
            if encrypted:
                expected_keys.update({"salt", "nonce", "iterations"})
            if (
                set(manifest) != expected_keys
                or manifest["format"] != "mcm-ems-postgresql"
                or manifest["version"] != FORMAT_VERSION
                or not isinstance(encrypted, bool)
                or not isinstance(manifest["payload_size"], int)
                or isinstance(manifest["payload_size"], bool)
                or manifest["payload_size"] < 1
                or manifest["payload_size"] > MAX_BACKUP_SIZE
                or payload_info.file_size != manifest["payload_size"]
                or not isinstance(manifest["payload_sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", manifest["payload_sha256"])
                or not isinstance(manifest["signature"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", manifest["signature"])
                or (
                    encrypted
                    and (
                        not isinstance(manifest["salt"], str)
                        or not re.fullmatch(r"[a-f0-9]{32}", manifest["salt"])
                        or not isinstance(manifest["nonce"], str)
                        or not re.fullmatch(r"[a-f0-9]{24}", manifest["nonce"])
                        or not isinstance(manifest["iterations"], int)
                        or manifest["iterations"] != PBKDF2_ITERATIONS
                    )
                )
                or not hmac.compare_digest(
                    manifest["signature"], _manifest_signature(manifest)
                )
            ):
                raise BackupError("The uploaded backup file is invalid.")
            return manifest, expected_payload
    except BackupError:
        raise
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as error:
        raise BackupError("The uploaded backup file is invalid.") from error


def _copy_verified_payload(archive, manifest, payload_name, destination):
    digest = hashlib.sha256()
    size = 0
    try:
        with archive.open(payload_name) as source, destination.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BACKUP_SIZE:
                    raise BackupError("The uploaded backup file is invalid.")
                digest.update(chunk)
                target.write(chunk)
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        destination.unlink(missing_ok=True)
        raise BackupError("The uploaded backup file is invalid.") from error
    if (
        size != manifest["payload_size"]
        or not hmac.compare_digest(digest.hexdigest(), manifest["payload_sha256"])
    ):
        destination.unlink(missing_ok=True)
        raise BackupError("The uploaded backup file is invalid.")


def _verify_dump(dump_path, url):
    _run_tool(
        [_utility_path("pg_restore"), "--list", str(dump_path)],
        url,
        timeout=120,
    )


def _metadata_path(backup_id):
    if not BACKUP_ID_PATTERN.fullmatch(backup_id):
        return None
    return _backup_directory() / f"{backup_id}.json"


def _read_metadata(backup_id):
    if _uses_supabase_storage():
        if not BACKUP_ID_PATTERN.fullmatch(backup_id):
            return None
        try:
            record = db.session.get(DatabaseBackup, backup_id)
        except SQLAlchemyError as error:
            db.session.rollback()
            logger.error("Could not read persistent backup metadata: error_type=%s", type(error).__name__)
            raise BackupError("Backup information is temporarily unavailable.") from error
        if record is None:
            return None
        return _metadata_from_record(record)

    metadata_path = _metadata_path(backup_id)
    if metadata_path is None or metadata_path.is_symlink() or not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.error("Could not read backup metadata: error_type=%s", type(error).__name__)
        return None
    expected_filename = metadata.get("filename") if isinstance(metadata, dict) else None
    if (
        not isinstance(metadata, dict)
        or metadata.get("id") != backup_id
        or metadata.get("status") not in {"successful", "failed"}
        or not isinstance(metadata.get("created_at"), str)
        or not isinstance(metadata.get("created_by"), str)
        or not isinstance(metadata.get("encrypted"), bool)
        or not isinstance(metadata.get("file_size"), int)
        or isinstance(metadata.get("file_size"), bool)
        or metadata["file_size"] < 0
        or not isinstance(expected_filename, str)
        or secure_filename(expected_filename) != expected_filename
        or Path(expected_filename).name != expected_filename
        or not expected_filename.endswith(PACKAGE_EXTENSION)
    ):
        return None
    return metadata


def _metadata_from_record(record):
    created_at = record.created_at
    expected_storage_key = _storage_key(record.id)
    if (
        not isinstance(record.filename, str)
        or secure_filename(record.filename) != record.filename
        or Path(record.filename).name != record.filename
        or not record.filename.endswith(PACKAGE_EXTENSION)
        or record.status not in {"successful", "failed"}
        or not isinstance(record.file_size, int)
        or isinstance(record.file_size, bool)
        or record.file_size < 0
        or (
            record.status == "successful"
            and record.file_size > MAX_REMOTE_PACKAGE_SIZE
        )
        or record.storage_key != expected_storage_key
        or not isinstance(record.verified, bool)
    ):
        raise BackupError("Stored backup information is invalid.")
    if created_at is None:
        raise BackupError("Stored backup information is invalid.")
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return {
        "id": record.id,
        "filename": record.filename,
        "created_at": created_at.isoformat(),
        "file_size": record.file_size,
        "created_by": record.created_by,
        "encrypted": record.encrypted,
        "status": record.status,
        "storage_key": record.storage_key,
        "verified": record.verified,
    }


def _write_metadata(metadata):
    if _uses_supabase_storage():
        try:
            record = db.session.get(DatabaseBackup, metadata["id"])
            if record is None:
                record = DatabaseBackup(id=metadata["id"])
                db.session.add(record)
            created_at = datetime.fromisoformat(metadata["created_at"])
            record.filename = metadata["filename"]
            record.created_at = created_at
            record.file_size = metadata["file_size"]
            record.created_by = metadata["created_by"]
            record.encrypted = metadata["encrypted"]
            record.status = metadata["status"]
            record.storage_key = metadata.get("storage_key")
            record.verified = metadata.get("verified", False)
            db.session.commit()
        except SQLAlchemyError as error:
            db.session.rollback()
            logger.error("Could not write persistent backup metadata: error_type=%s", type(error).__name__)
            raise BackupError("Backup information could not be saved.") from error
        return

    metadata_path = _metadata_path(metadata["id"])
    temporary_path = metadata_path.with_name(
        f".{metadata['id']}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary_path.open("x", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=True)
        if os.name != "nt":
            temporary_path.chmod(0o600)
        os.replace(temporary_path, metadata_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _backup_file(metadata):
    directory = _backup_directory()
    path = directory / metadata["filename"]
    if path.is_symlink() or not path.is_file() or path.resolve().parent != directory:
        return None
    return path


def backup_overview():
    try:
        database_name = db.engine.url.database if db.engine.dialect.name == "postgresql" else None
    except SQLAlchemyError:
        database_name = None
    metadata_available = True
    try:
        all_backups = list_backups(limit=None)
    except BackupError:
        all_backups = []
        metadata_available = False
    backups = all_backups[:MAX_HISTORY_ITEMS]
    successful = [item for item in all_backups if item["status"] == "successful"]
    latest = successful[0] if successful else None
    storage_available = False
    if _uses_supabase_storage():
        try:
            _backup_storage_bucket().list("", {"limit": 1})
            storage_available = True
        except BackupError:
            pass
        except Exception as error:
            logger.error("Could not check Supabase backup storage: error_type=%s", type(error).__name__)
    else:
        try:
            _backup_directory()
            storage_available = True
        except BackupError:
            pass
    try:
        db.session.execute(text("SELECT 1"))
        connection_status = "Connected"
    except SQLAlchemyError:
        db.session.rollback()
        connection_status = "Unavailable"
    restore_available = False
    try:
        restore_available = bool(
            db.session.execute(
                text(
                    "SELECT rolcreatedb FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            ).scalar()
        )
    except SQLAlchemyError:
        db.session.rollback()
    return {
        "database_name": database_name or "Unavailable",
        "connection_status": connection_status,
        "backups": backups,
        "backup_count": len(successful),
        "latest_backup": latest,
        "utilities_available": all(
            _has_utility(name) for name in ("pg_dump", "pg_restore")
        ),
        "storage_available": storage_available,
        "backup_service_available": storage_available
        and metadata_available
        and connection_status == "Connected"
        and all(_has_utility(name) for name in ("pg_dump", "pg_restore")),
        "storage_backend": "supabase" if _uses_supabase_storage() else "local",
        "restore_available": restore_available,
    }


def _has_utility(name):
    try:
        _utility_path(name)
        return True
    except BackupError:
        return False


def list_backups(limit=MAX_HISTORY_ITEMS):
    if _uses_supabase_storage():
        try:
            records = db.session.execute(
                select(DatabaseBackup).order_by(DatabaseBackup.created_at.desc())
            ).scalars().all()
        except SQLAlchemyError as error:
            db.session.rollback()
            logger.error("Could not list persistent backup metadata: error_type=%s", type(error).__name__)
            raise BackupError("Backup information is temporarily unavailable.") from error
        backups = [_metadata_from_record(record) for record in records]
        backups.sort(key=lambda item: item["created_at"], reverse=True)
        return backups if limit is None else backups[:limit]

    directory = _backup_directory()
    backups = []
    for metadata_path in directory.glob("*.json"):
        backup_id = metadata_path.stem
        if not BACKUP_ID_PATTERN.fullmatch(backup_id):
            continue
        metadata = _read_metadata(backup_id)
        if metadata is None:
            logger.warning("Skipped invalid database backup metadata.")
            continue
        backup_path = _backup_file(metadata) if metadata["status"] == "successful" else None
        status = metadata["status"] if backup_path else (
            "missing" if metadata["status"] == "successful" else "failed"
        )
        backups.append(
            {
                **metadata,
                "status": status,
                "file_size": backup_path.stat().st_size if backup_path else metadata.get("file_size", 0),
                "path": backup_path,
            }
        )
    backups.sort(key=lambda item: item["created_at"], reverse=True)
    return backups if limit is None else backups[:limit]


def create_backup(created_by, password=None):
    if password is not None and len(password) < PASSWORD_MIN_LENGTH:
        raise BackupError("Use an encryption password with at least 12 characters.")
    with LOCAL_OPERATION_LOCK:
        return _create_backup_internal(created_by, password)


def _create_backup_internal(created_by, password=None):
    url = _database_url()
    backup_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    filename = f"ems-database-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{backup_id[:8]}{PACKAGE_EXTENSION}"
    directory = _backup_directory()
    package_path = directory / filename
    metadata = {
        "id": backup_id,
        "filename": filename,
        "created_at": created_at,
        "file_size": 0,
        "created_by": created_by,
        "encrypted": bool(password),
        "status": "failed",
        "storage_key": _storage_key(backup_id) if _uses_supabase_storage() else None,
        "verified": False,
    }
    upload_attempted = False
    try:
        dump_utility = _utility_path("pg_dump")
        with tempfile.TemporaryDirectory(prefix=".create-", dir=directory) as temp:
            dump_path = Path(temp) / "database.dump"
            staged_package = Path(temp) / filename
            arguments = [
                dump_utility,
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--file",
                str(dump_path),
            ]
            _run_tool(arguments, url)
            if not dump_path.is_file() or not dump_path.stat().st_size:
                raise BackupError("Unable to create backup. Please try again.")
            _verify_dump(dump_path, url)
            if dump_path.stat().st_size > MAX_BACKUP_SIZE:
                raise BackupError("The generated backup exceeds the 512 MB size limit.")
            if (
                _uses_supabase_storage()
                and dump_path.stat().st_size > MAX_REMOTE_PACKAGE_SIZE
            ):
                raise BackupError(
                    "The final backup package exceeds the 50 MB Supabase Storage limit."
                )
            _write_package(dump_path, staged_package, password)
            if os.name != "nt":
                staged_package.chmod(0o600)
            package_size = staged_package.stat().st_size
            if package_size > _package_size_limit():
                raise BackupError(_package_size_error())
            if _uses_supabase_storage():
                upload_attempted = True
                _upload_package(staged_package, metadata["storage_key"])
            else:
                os.replace(staged_package, package_path)
        metadata["status"] = "successful"
        metadata["file_size"] = (
            package_size if _uses_supabase_storage() else package_path.stat().st_size
        )
        metadata["verified"] = True
        _write_metadata(metadata)
        return metadata
    except Exception as error:
        package_path.unlink(missing_ok=True)
        if upload_attempted and metadata.get("storage_key"):
            try:
                _delete_package(metadata["storage_key"])
            except BackupError:
                logger.error("Could not clean up an incomplete backup object.")
        logger.error("Database backup failed: error_type=%s", type(error).__name__)
        try:
            _write_metadata(metadata)
        except (OSError, BackupError):
            logger.error("Could not record failed database backup metadata.")
        if isinstance(error, BackupError):
            raise
        raise BackupError("Unable to create backup. Please try again.") from error


def get_backup(backup_id):
    metadata = _read_metadata(backup_id)
    if metadata is None or metadata["status"] != "successful":
        return None
    if _uses_supabase_storage():
        return metadata
    path = _backup_file(metadata)
    if path is None:
        return None
    return {**metadata, "path": path}


def delete_backup(backup_id):
    metadata = _read_metadata(backup_id)
    if metadata is None:
        return False
    if _uses_supabase_storage():
        if metadata["status"] == "successful" and metadata.get("storage_key"):
            _delete_package(metadata["storage_key"])
        try:
            record = db.session.get(DatabaseBackup, backup_id)
            if record is not None:
                db.session.delete(record)
                db.session.commit()
        except SQLAlchemyError as error:
            db.session.rollback()
            logger.error("Could not delete persistent backup metadata: error_type=%s", type(error).__name__)
            raise BackupError("Backup information could not be deleted.") from error
        return True

    backup_path = _backup_file(metadata) if metadata["status"] == "successful" else None
    if backup_path:
        backup_path.unlink()
    metadata_path = _metadata_path(backup_id)
    metadata_path.unlink(missing_ok=True)
    return True


def _create_destination_database(url, database_name):
    maintenance_url = url.set(database="postgres")
    engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            quoted_name = connection.dialect.identifier_preparer.quote(database_name)
            connection.execute(text(f"CREATE DATABASE {quoted_name}"))
    finally:
        engine.dispose()


def _drop_destination_database(url, database_name):
    maintenance_url = url.set(database="postgres")
    engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            quoted_name = connection.dialect.identifier_preparer.quote(database_name)
            connection.execute(text(f"DROP DATABASE IF EXISTS {quoted_name}"))
    finally:
        engine.dispose()


def restore_backup(upload_stream, database_name, password=""):
    database_name = database_name.strip()
    if (
        not DATABASE_NAME_PATTERN.fullmatch(database_name)
        or database_name.lower() in {"postgres", "template0", "template1"}
    ):
        raise BackupError(
            "Enter a new database name using letters, numbers, and underscores."
        )
    url = _database_url()
    if database_name.casefold() == (url.database or "").casefold():
        raise BackupError("The active database cannot be used as the restore destination.")

    with LOCAL_OPERATION_LOCK:
        return _restore_backup_internal(upload_stream, database_name, password, url)


def _restore_backup_internal(upload_stream, database_name, password, url):
    directory = _backup_directory()
    try:
        with tempfile.TemporaryDirectory(prefix=".restore-", dir=directory) as temp:
            temp_directory = Path(temp)
            package_path = temp_directory / "uploaded.emsbackup"
            size = 0
            with package_path.open("xb") as staged_upload:
                while chunk := upload_stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_PACKAGE_SIZE:
                        raise BackupError("The uploaded backup file exceeds the 512 MB size limit.")
                    staged_upload.write(chunk)
            if size < 1:
                raise BackupError("The uploaded backup file is invalid.")

            manifest, payload_name = _read_manifest(package_path)
            payload_path = temp_directory / payload_name
            with zipfile.ZipFile(package_path) as package:
                _copy_verified_payload(
                    package,
                    manifest,
                    payload_name,
                    payload_path,
                )
            dump_path = temp_directory / "restore.dump"
            if manifest["encrypted"]:
                try:
                    _decrypt_file(
                        payload_path,
                        dump_path,
                        password,
                        bytes.fromhex(manifest["salt"]),
                        bytes.fromhex(manifest["nonce"]),
                    )
                except BackupError:
                    raise
                except Exception as error:
                    raise BackupError(
                        "The uploaded backup file is invalid or its encryption password is incorrect."
                    ) from error
            else:
                os.replace(payload_path, dump_path)
            _verify_dump(dump_path, url)

            try:
                _create_destination_database(url, database_name)
            except SQLAlchemyError as error:
                logger.error(
                    "Could not create database restore destination: error_type=%s",
                    type(error).__name__,
                )
                raise BackupError(
                    "Could not create a new restore database. Your active database has not been changed."
                ) from error

            try:
                target_url = url.set(database=database_name)
                arguments = [
                    _utility_path("pg_restore"),
                    "--no-owner",
                    "--no-acl",
                    "--exit-on-error",
                    "--single-transaction",
                    "-d",
                    database_name,
                    str(dump_path),
                ]
                _run_tool(arguments, target_url)
            except BackupError as error:
                try:
                    _drop_destination_database(url, database_name)
                except SQLAlchemyError as cleanup_error:
                    logger.error(
                        "Could not remove failed restore destination: error_type=%s",
                        type(cleanup_error).__name__,
                    )
                raise BackupError(
                    "Unable to restore the backup. Your active database has not been changed."
                ) from error
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as error:
        logger.error("Database restore failed: error_type=%s", type(error).__name__)
        raise BackupError("The uploaded backup file is invalid.") from error
    return database_name
