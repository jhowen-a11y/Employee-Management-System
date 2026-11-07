import json
import logging
import os
from urllib.parse import urlparse

import httpx
from flask import current_app

from services import database_backups
from services.database_backups import BackupError


logger = logging.getLogger(__name__)


def worker_mode():
    return bool(current_app.config.get("BACKUP_WORKER_URL")) or (
        os.getenv("VERCEL") == "1"
    )


def _worker_settings():
    base_url = (
        current_app.config.get("BACKUP_WORKER_URL")
        or os.getenv("BACKUP_WORKER_URL", "")
    ).strip().rstrip("/")
    token = current_app.config.get("BACKUP_WORKER_TOKEN") or os.getenv(
        "BACKUP_WORKER_TOKEN", ""
    )
    if not base_url:
        raise BackupError("The production backup worker is not configured.")
    if not base_url.startswith("https://"):
        raise BackupError("The backup worker must use a secure HTTPS address.")
    if not token:
        raise BackupError("The production backup worker is not configured.")
    return base_url, token


def _request(method, endpoint, *, json_body=None, timeout=30, missing_ok=False):
    base_url, token = _worker_settings()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=10),
            follow_redirects=False,
        ) as client:
            response = client.request(
                method,
                f"{base_url}/internal/v1/{endpoint.lstrip('/')}",
                headers={"Authorization": f"Bearer {token}"},
                json=json_body,
            )
    except httpx.HTTPError as error:
        logger.error("Backup worker request failed: error_type=%s", type(error).__name__)
        raise BackupError(
            "The backup service could not be reached. Please try again."
        ) from error
    if missing_ok and response.status_code == 404:
        return None
    return _parse_response(response)


def _parse_response(response):
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        payload = {}
    if not response.is_success:
        message = payload.get("error") if isinstance(payload, dict) else None
        if response.status_code in {400, 404, 409, 413} and isinstance(message, str):
            raise BackupError(message)
        logger.error(
            "Backup worker returned an error: status_code=%s",
            response.status_code,
        )
        raise BackupError(
            "The backup service could not complete the request. Please try again."
        )
    return payload


def backup_overview():
    if not worker_mode():
        return database_backups.backup_overview()
    try:
        overview = _request("GET", "overview")
        overview["jobs"] = _request("GET", "jobs").get("jobs", [])
        overview["worker_mode"] = True
        return overview
    except BackupError as error:
        logger.error(
            "Backup worker overview unavailable: error_type=%s message=%s",
            type(error).__name__,
            error.public_message,
        )
        return {
            "database_name": "Unavailable",
            "connection_status": "Unavailable",
            "backups": [],
            "backup_count": 0,
            "latest_backup": None,
            "utilities_available": False,
            "storage_available": False,
            "metadata_available": False,
            "backup_service_available": False,
            "storage_backend": "supabase",
            "worker_mode": True,
            "worker_error": error.public_message,
            "jobs": [],
        }


def list_backups(limit=None):
    if not worker_mode():
        return database_backups.list_backups(limit=limit)
    result = _request("GET", "backups")
    backups = result.get("backups")
    if not isinstance(backups, list):
        raise BackupError("The backup service returned invalid backup information.")
    return backups if limit is None else backups[:limit]


def list_jobs():
    if not worker_mode():
        return []
    result = _request("GET", "jobs")
    jobs = result.get("jobs")
    if not isinstance(jobs, list):
        raise BackupError("The backup service returned invalid job information.")
    return jobs


def create_backup(created_by, password=None):
    if not worker_mode():
        return database_backups.create_backup(created_by, password)
    result = _request(
        "POST",
        "jobs/create",
        json_body={"created_by": created_by, "password": password or ""},
        timeout=30,
    )
    if not isinstance(result.get("job"), dict):
        raise BackupError("The backup service returned an invalid job response.")
    return result["job"]


def restore_backup(
    upload_stream,
    database_name,
    password="",
    backup_id=None,
    created_by="administrator",
):
    if not worker_mode():
        if backup_id:
            backup = database_backups.get_backup(backup_id)
            if backup is None:
                raise BackupError("The selected backup is unavailable.")
            with backup["path"].open("rb") as package:
                return database_backups.restore_backup(
                    package,
                    database_name,
                    password,
                )
        return database_backups.restore_backup(
            upload_stream,
            database_name,
            password,
        )

    if not backup_id:
        raise BackupError(
            "In production, select an existing private backup from the list."
        )
    result = _request(
        "POST",
        "jobs/restore",
        json_body={
            "backup_id": backup_id,
            "database_name": database_name,
            "password": password,
            "created_by": created_by,
        },
        timeout=30,
    )
    if not isinstance(result.get("job"), dict):
        raise BackupError("The backup service returned an invalid job response.")
    return result["job"]


def get_backup(backup_id):
    if not worker_mode():
        return database_backups.get_backup(backup_id)
    if not database_backups.BACKUP_ID_PATTERN.fullmatch(backup_id):
        return None
    result = _request("GET", f"backups/{backup_id}", missing_ok=True)
    if result is None:
        return None
    backup = result.get("backup")
    return backup if isinstance(backup, dict) else None


def download_backup(backup_id):
    if not worker_mode():
        backup = database_backups.get_backup(backup_id)
        if backup is None:
            return None, None
        return backup, None
    if not database_backups.BACKUP_ID_PATTERN.fullmatch(backup_id):
        return None, None
    result = _request(
        "GET",
        f"backups/{backup_id}/download-url",
        missing_ok=True,
    )
    if result is None:
        return None, None
    backup = result.get("backup")
    signed_url = result.get("url")
    supabase_url = os.getenv("SUPABASE_URL", "")
    parsed_url = urlparse(signed_url) if isinstance(signed_url, str) else None
    expected_host = urlparse(supabase_url).netloc
    if (
        not isinstance(backup, dict)
        or not parsed_url
        or parsed_url.scheme != "https"
        or parsed_url.netloc != expected_host
    ):
        raise BackupError("The private backup download link is invalid.")
    return backup, signed_url


def delete_backup(backup_id):
    if not worker_mode():
        return database_backups.delete_backup(backup_id)
    if not database_backups.BACKUP_ID_PATTERN.fullmatch(backup_id):
        return False
    response = _request(
        "DELETE",
        f"backups/{backup_id}",
        missing_ok=True,
    )
    if response is None:
        return False
    return bool(response.get("deleted"))
