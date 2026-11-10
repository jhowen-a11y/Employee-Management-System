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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from flask import current_app
from supabase import create_client
from werkzeug.utils import secure_filename

from models import db


logger = logging.getLogger(__name__)
DEFAULT_BACKUP_BUCKET = "database-backups"
FORMAT_VERSION = 1
MAX_BACKUP_SIZE = 512 * 1024 * 1024
MAX_MANIFEST_SIZE = 16 * 1024
MAX_HISTORY_ITEMS = 200
BACKUP_HISTORY_CACHE_SECONDS = 10
PBKDF2_ITERATIONS = 600_000
PASSWORD_MIN_LENGTH = 12
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
BACKUP_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
PACKAGE_EXTENSION = ".emsbackup"
_backup_bucket_cache = {}
_backup_bucket_cache_lock = threading.Lock()
_backup_history_cache = {}
_backup_history_cache_lock = threading.Lock()


class BackupError(Exception):
    def __init__(self, public_message):
        super().__init__(public_message)
        self.public_message = public_message


def backup_bucket_name():
    return os.getenv("SUPABASE_BACKUP_BUCKET", DEFAULT_BACKUP_BUCKET)


def backup_bucket():
    project_url = os.getenv("SUPABASE_URL")
    secret_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SECRET_KEY")
    )
    if not project_url:
        raise BackupError("SUPABASE_URL is not configured.")
    if not secret_key:
        raise BackupError(
            "Set SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY."
        )

    bucket_name = backup_bucket_name()
    cache_key = (
        threading.get_ident(),
        project_url,
        bucket_name,
        hashlib.sha256(secret_key.encode()).digest(),
    )
    with _backup_bucket_cache_lock:
        cached_bucket = _backup_bucket_cache.get(cache_key)
    if cached_bucket is not None:
        return cached_bucket

    try:
        bucket = create_client(project_url, secret_key).storage.from_(bucket_name)
    except Exception as error:
        raise BackupError("Could not connect to Supabase Storage.") from error
    with _backup_bucket_cache_lock:
        _backup_bucket_cache[cache_key] = bucket
    return bucket


def raise_storage_error(message, error):
    logger.error(
        "%s: error_type=%s",
        message,
        type(error).__name__,
    )
    raise BackupError(message) from error


def database_url():
    url = db.engine.url
    if url.get_backend_name() != "postgresql":
        raise BackupError("Database backup and restore require PostgreSQL.")
    return url


def utility_path(name):
    config_key = {
        "pg_dump": "PG_DUMP_PATH",
        "pg_restore": "PG_RESTORE_PATH",
        "psql": "PSQL_PATH",
    }.get(name)
    if config_key is None:
        raise BackupError("Unsupported PostgreSQL utility.")
    configured = current_app.config.get(config_key) or os.getenv(config_key)
    utility = None
    if configured:
        configured_path = Path(configured).expanduser()
        utility = (
            str(configured_path)
            if configured_path.is_file()
            else shutil.which(configured)
        )
    else:
        versioned_paths = sorted(
            Path("/usr/lib/postgresql").glob(f"*/bin/{name}"),
            reverse=True,
        )
        utility = (
            str(versioned_paths[0])
            if versioned_paths
            else shutil.which(name)
        )
    if not utility or not Path(utility).is_file():
        raise BackupError(
            "PostgreSQL backup utilities are unavailable on this server."
        )
    return str(Path(utility).resolve())


def tool_environment(url):
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
            logger.error(
                "Could not prepare PostgreSQL credentials: error_type=%s",
                type(error).__name__,
            )
            raise BackupError(
                "Unable to complete the database operation. Please try again."
            ) from error
    return environment, passfile


def tool_arguments(arguments, url):
    if Path(arguments[0]).stem.lower() != "psql":
        return arguments
    database = url.set(
        drivername="postgresql",
        password=None,
    ).render_as_string(hide_password=False)
    return [*arguments, "--dbname", database]


def run_tool(arguments, url, timeout=900):
    passfile = None
    try:
        environment, passfile = tool_environment(url)
        result = subprocess.run(
            tool_arguments(arguments, url),
            check=False,
            capture_output=True,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.error(
            "PostgreSQL backup utility failed: error_type=%s",
            type(error).__name__,
        )
        raise BackupError(
            "Unable to complete the database operation. Please try again."
        ) from error
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
        error_output = result.stderr.decode("utf-8", errors="replace").strip()
        logger.error(
            "PostgreSQL backup utility returned an error: return_code=%s stderr=%s",
            result.returncode,
            error_output[-2000:] if error_output else "(no error output)",
        )
        raise BackupError(
            "PostgreSQL could not complete the database operation. "
            "Check the server logs for the database error."
        )
    return result


def password_key(password, salt):
    if len(password) < PASSWORD_MIN_LENGTH:
        raise BackupError("Use an encryption password with at least 12 characters.")
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    ).derive(password.encode("utf-8"))


def encrypt_file(source, destination, password, salt, nonce):
    encryptor = Cipher(
        algorithms.AES(password_key(password, salt)),
        modes.GCM(nonce),
    ).encryptor()
    with source.open("rb") as input_file, destination.open("wb") as output_file:
        while chunk := input_file.read(1024 * 1024):
            output_file.write(encryptor.update(chunk))
        output_file.write(encryptor.finalize())
        output_file.write(encryptor.tag)


def decrypt_file(source, destination, password, salt, nonce):
    size = source.stat().st_size
    if size < 16:
        raise BackupError("The uploaded backup file is invalid.")
    with source.open("rb") as input_file:
        input_file.seek(-16, os.SEEK_END)
        tag = input_file.read(16)
        input_file.seek(0)
        decryptor = Cipher(
            algorithms.AES(password_key(password, salt)),
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


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def manifest_signature(manifest):
    signing_key = current_app.config["SECRET_KEY"]
    if isinstance(signing_key, str):
        signing_key = signing_key.encode("utf-8")
    unsigned_manifest = {
        key: value for key, value in manifest.items() if key != "signature"
    }
    return hmac.new(
        signing_key,
        canonical_json(unsigned_manifest),
        hashlib.sha256,
    ).hexdigest()


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as backup_file:
        for chunk in iter(lambda: backup_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_package(dump_path, package_path, password):
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
        encrypt_file(dump_path, payload_path, password, salt, nonce)
        manifest.update(
            {
                "salt": salt.hex(),
                "nonce": nonce.hex(),
                "iterations": PBKDF2_ITERATIONS,
            }
        )
    manifest["payload_size"] = payload_path.stat().st_size
    if manifest["payload_size"] > MAX_BACKUP_SIZE:
        raise BackupError("The generated backup exceeds the 512 MB size limit.")
    manifest["payload_sha256"] = digest_file(payload_path)
    manifest["signature"] = manifest_signature(manifest)
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_STORED) as package:
        package.writestr(
            "manifest.json",
            canonical_json(manifest),
        )
        package.write(payload_path, "backup.enc" if password else "backup.dump")


def read_manifest(package):
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
                    manifest["signature"], manifest_signature(manifest)
                )
            ):
                raise BackupError("The uploaded backup file is invalid.")
            return manifest, expected_payload
    except BackupError:
        raise
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as error:
        raise BackupError("The uploaded backup file is invalid.") from error


def copy_verified_payload(archive, manifest, payload_name, destination):
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


def verify_dump(dump_path, url):
    return run_tool(
        [utility_path("pg_restore"), "--list", str(dump_path)],
        url,
        timeout=120,
    )


def write_restore_list(list_path, listing):
    excluded_markers = (
        "EVENT TRIGGER",
        " auth.",
        " storage.",
        "rls_auto_enable",
        "ensure_rls",
        "pgrst_drop_watch",
    )
    managed_object_markers = (
        " bucket_",
        " s3_",
        " vector_",
        " objects ",
        " buckets ",
        " migrations ",
        " prefixes ",
        " objects_id_seq",
        " webauthn_",
        " fido_",
        " sso_",
        " pgbouncer",
    )
    managed_owner_markers = (
        " supabase_admin",
        " supabase_storage_admin",
        " supabase_auth_admin",
        " supabase_realtime_admin",
    )
    try:
        with list_path.open("w", encoding="utf-8") as restore_list:
            for line in listing.stdout.decode("utf-8", errors="replace").splitlines(
                keepends=True
            ):
                normalized_line = " ".join(line.lower().split())
                is_non_public_schema = any(
                    f" {schema_name} " in f" {normalized_line} "
                    for schema_name in (
                        "pgbouncer",
                        "pg_catalog",
                        "information_schema",
                    )
                )
                is_managed_object = any(
                    marker in f" {normalized_line} "
                    for marker in managed_object_markers
                )
                is_managed_owner = any(
                    normalized_line.endswith(marker)
                    for marker in managed_owner_markers
                )
                if (
                    not is_non_public_schema
                    and not is_managed_object
                    and not is_managed_owner
                    and not any(
                    marker.lower() in normalized_line
                    for marker in excluded_markers
                    )
                ):
                    restore_list.write(line)
    except OSError as error:
        raise BackupError("Unable to prepare the database restore.") from error


def metadata_object_name(backup_id):
    if not BACKUP_ID_PATTERN.fullmatch(backup_id):
        return None
    return f"{backup_id}.json"


def read_metadata(backup_id):
    object_name = metadata_object_name(backup_id)
    if object_name is None:
        return None
    try:
        metadata_contents = backup_bucket().download(object_name)
    except Exception as error:
        if (
            getattr(error, "status_code", None) == 404
            or getattr(error, "status", None) == 404
        ):
            return None
        raise_storage_error("Could not read database backup metadata", error)
    try:
        metadata = json.loads(metadata_contents)
    except (TypeError, ValueError, UnicodeDecodeError):
        logger.warning("Skipped invalid database backup metadata.")
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


def write_metadata(metadata):
    object_name = metadata_object_name(metadata["id"])
    try:
        backup_bucket().upload(
            object_name,
            json.dumps(metadata, ensure_ascii=True).encode("utf-8"),
            {"content-type": "application/json", "upsert": "true"},
        )
    except Exception as error:
        raise_storage_error("Could not save database backup metadata", error)


def backup_overview():
    database_name = (
        db.engine.url.database
        if db.engine.dialect.name == "postgresql"
        else None
    )
    all_backups = list_backups(limit=None)
    backups = all_backups[:MAX_HISTORY_ITEMS]
    successful = [item for item in all_backups if item["status"] == "successful"]
    latest = successful[0] if successful else None
    return {
        "database_name": database_name or "Unavailable",
        "connection_status": "Unavailable",
        "backups": backups,
        "backup_count": len(successful),
        "latest_backup": latest,
        "utilities_available": all(
            has_utility(name) for name in ("pg_dump", "pg_restore", "psql")
        ),
    }


def has_utility(name):
    try:
        utility_path(name)
        return True
    except BackupError:
        return False


def list_backups(limit=MAX_HISTORY_ITEMS):
    bucket = backup_bucket()
    cache_key = (id(bucket), limit)
    now = datetime.now(timezone.utc).timestamp()
    with _backup_history_cache_lock:
        cached = _backup_history_cache.get(cache_key)
        if cached and now - cached[0] < BACKUP_HISTORY_CACHE_SECONDS:
            return [*cached[1]]

    backups = []
    object_names = set()
    offset = 0
    page_size = 100
    try:
        while True:
            page = bucket.list("", {"limit": page_size, "offset": offset})
            object_names.update(
                item["name"]
                for item in page
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            )
            if len(page) < page_size:
                break
            offset += len(page)
    except Exception as error:
        raise_storage_error("Could not list database backups", error)

    metadata_ids = [
        metadata_name[:-5]
        for metadata_name in object_names
        if metadata_name.endswith(".json")
        and BACKUP_ID_PATTERN.fullmatch(metadata_name[:-5])
    ]

    def load_metadata(backup_id):
        try:
            return backup_id, read_metadata(backup_id)
        except BackupError as error:
            logger.warning(
                "Skipped unreadable database backup metadata: "
                "backup_id=%s error_type=%s",
                backup_id,
                type(error).__name__,
            )
            return backup_id, None

    with ThreadPoolExecutor(max_workers=min(8, len(metadata_ids) or 1)) as executor:
        metadata_results = executor.map(load_metadata, metadata_ids)

    for backup_id, metadata in metadata_results:
        if metadata is None:
            logger.warning("Skipped invalid database backup metadata.")
            continue
        has_package = metadata["filename"] in object_names
        status = (
            metadata["status"]
            if has_package or metadata["status"] == "failed"
            else "missing"
        )
        backups.append(
            {
                **metadata,
                "status": status,
                "file_size": metadata.get("file_size", 0),
            }
        )
    backups.sort(key=lambda item: item["created_at"], reverse=True)
    result = backups if limit is None else backups[:limit]
    with _backup_history_cache_lock:
        _backup_history_cache[cache_key] = (now, [*result])
    return result


def clear_backup_history_cache():
    with _backup_history_cache_lock:
        _backup_history_cache.clear()


def create_backup(created_by, password=None):
    if password is not None and len(password) < PASSWORD_MIN_LENGTH:
        raise BackupError("Use an encryption password with at least 12 characters.")
    url = database_url()
    backup_id = uuid.uuid4().hex
    created_at_time = datetime.now(timezone.utc)
    created_at = created_at_time.isoformat()
    filename = (
        f"ems-database-{created_at_time:%Y%m%dT%H%M%SZ}-"
        f"{backup_id[:8]}{PACKAGE_EXTENSION}"
    )
    metadata = {
        "id": backup_id,
        "filename": filename,
        "created_at": created_at,
        "file_size": 0,
        "created_by": created_by,
        "encrypted": bool(password),
        "status": "failed",
    }
    bucket = None
    try:
        bucket = backup_bucket()
        dump_utility = utility_path("pg_dump")
        with tempfile.TemporaryDirectory(prefix="ems-backup-create-") as temp:
            dump_path = Path(temp) / "database.dump"
            staged_package = Path(temp) / filename
            arguments = [
                dump_utility,
                "--format=custom",
                "--schema=public",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(dump_path),
            ]
            run_tool(arguments, url)
            if not dump_path.is_file() or not dump_path.stat().st_size:
                raise BackupError("Unable to create backup. Please try again.")
            verify_dump(dump_path, url)
            if dump_path.stat().st_size > MAX_BACKUP_SIZE:
                raise BackupError("The generated backup exceeds the 512 MB size limit.")
            write_package(dump_path, staged_package, password)
            metadata["file_size"] = staged_package.stat().st_size
            with staged_package.open("rb") as package_file:
                bucket.upload(
                    filename,
                    package_file,
                    {"content-type": "application/zip", "upsert": "false"},
                )
        metadata["status"] = "successful"
        write_metadata(metadata)
        clear_backup_history_cache()
        return metadata
    except Exception as error:
        logger.error("Database backup failed: error_type=%s", type(error).__name__)
        if bucket is not None:
            try:
                bucket.remove([filename])
            except Exception as cleanup_error:
                logger.error(
                    "Could not remove incomplete database backup from "
                    "Supabase Storage: "
                    "error_type=%s",
                    type(cleanup_error).__name__,
                )
        try:
            write_metadata(metadata)
        except BackupError:
            logger.error("Could not record failed database backup metadata.")
        if isinstance(error, BackupError):
            raise
        raise BackupError("Unable to create backup. Please try again.") from error


def get_backup(backup_id):
    metadata = read_metadata(backup_id)
    if metadata is None or metadata["status"] != "successful":
        return None
    try:
        package = backup_bucket().download(metadata["filename"])
    except Exception as error:
        if (
            getattr(error, "status_code", None) == 404
            or getattr(error, "status", None) == 404
        ):
            return None
        raise_storage_error("Could not download database backup", error)
    if not package:
        return None
    return {**metadata, "stream": BytesIO(package)}


def delete_backup(backup_id):
    metadata = read_metadata(backup_id)
    if metadata is None:
        return False
    object_name = metadata_object_name(backup_id)
    object_names = [object_name, metadata["filename"]]
    try:
        backup_bucket().remove(object_names)
    except Exception as error:
        raise_storage_error("Could not delete database backup", error)
    clear_backup_history_cache()
    return True


def restore_backup(upload_stream, password=""):
    url = database_url()

    try:
        with tempfile.TemporaryDirectory(prefix="ems-backup-restore-") as temp:
            temp_directory = Path(temp)
            package_path = temp_directory / "uploaded.emsbackup"
            size = 0
            with package_path.open("xb") as staged_upload:
                while chunk := upload_stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BACKUP_SIZE + MAX_MANIFEST_SIZE + 1024 * 1024:
                        raise BackupError("The uploaded backup file is too large.")
                    staged_upload.write(chunk)
            if size < 1:
                raise BackupError("The uploaded backup file is invalid.")

            manifest, payload_name = read_manifest(package_path)
            payload_path = temp_directory / payload_name
            with zipfile.ZipFile(package_path) as package:
                copy_verified_payload(
                    package,
                    manifest,
                    payload_name,
                    payload_path,
                )
            dump_path = temp_directory / "restore.dump"
            if manifest["encrypted"]:
                try:
                    decrypt_file(
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
                        "The uploaded backup file is invalid or its encryption "
                        "password is incorrect."
                    ) from error
            else:
                os.replace(payload_path, dump_path)
            listing = verify_dump(dump_path, url)
            restore_list_path = temp_directory / "restore.list"
            write_restore_list(restore_list_path, listing)

            generated_sql_path = temp_directory / "generated_restore.sql"
            generate_restore_sql = [
                utility_path("pg_restore"),
                "--schema=public",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "--clean",
                "--if-exists",
                "--file",
                str(generated_sql_path),
                "--use-list",
                str(restore_list_path),
                str(dump_path),
            ]
            run_tool(generate_restore_sql, url)
            if (
                not generated_sql_path.is_file()
                or not generated_sql_path.stat().st_size
            ):
                raise BackupError("Unable to prepare the database restore.")

            restore_sql_path = temp_directory / "restore.sql"
            with restore_sql_path.open("wb") as restore_sql:
                restore_sql.write(b"SET LOCAL lock_timeout = '10s';\n")
                restore_sql.write(b"SET LOCAL statement_timeout = '10min';\n")
                restore_sql.write(b"DROP SCHEMA public CASCADE;\n")
                restore_sql.write(b"CREATE SCHEMA public;\n")
                with generated_sql_path.open("rb") as generated_sql:
                    restore_sql.write(generated_sql.read())

            try:
                db.session.remove()
                db.engine.dispose()
                run_tool(
                    [
                        utility_path("psql"),
                        "--set=ON_ERROR_STOP=on",
                        "--single-transaction",
                        "--file",
                        str(restore_sql_path),
                    ],
                    url,
                    timeout=660,
                )
            except BackupError as error:
                raise BackupError(
                    "Unable to restore the backup. The transaction rolled back, "
                    "so the active database was not changed."
                ) from error
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as error:
        logger.error("Database restore failed: error_type=%s", type(error).__name__)
        raise BackupError("The uploaded backup file is invalid.") from error
    return url.database
