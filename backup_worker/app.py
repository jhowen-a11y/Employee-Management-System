import hmac
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import urljoin

from flask import Flask, abort, current_app, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException
from models import db
from models.database_backup import DatabaseBackupJob
from services.database_backups import (
    BackupError,
    _download_package,
    _backup_storage_bucket,
    backup_overview,
    create_backup,
    delete_backup,
    get_backup,
    list_backups,
    restore_backup,
)


logger = logging.getLogger(__name__)
JOB_STATUSES = {"queued", "running", "successful", "failed"}
_job_queue_lock = threading.Lock()


def _job_data(job):
    created_at = job.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return {
        "id": job.id,
        "operation": job.operation,
        "status": job.status,
        "created_at": created_at.isoformat(),
        "created_by": job.created_by,
        "backup_id": job.backup_id,
        "destination_database": job.destination_database,
        "message": job.message,
    }


def _save_job_result(app, job_id, status, message, backup_id=None):
    with app.app_context():
        try:
            job = db.session.get(DatabaseBackupJob, job_id)
            if job is None:
                return
            job.status = status
            job.message = message
            job.backup_id = backup_id or job.backup_id
            job.updated_at = datetime.now(timezone.utc)
            db.session.commit()
        except SQLAlchemyError as error:
            db.session.rollback()
            logger.error(
                "Could not update backup job: error_type=%s",
                type(error).__name__,
            )


def _execute_job(app, job_id, operation, created_by, password, backup_id, database_name):
    _save_job_result(app, job_id, "running", "Operation in progress.")
    try:
        with app.app_context():
            if operation == "create":
                backup = create_backup(created_by, password or None)
                result_backup_id = backup["id"]
                message = "Backup created and verified."
            else:
                backup = get_backup(backup_id)
                if backup is None or backup.get("status") != "successful":
                    raise BackupError("The selected backup is unavailable.")
                package = _download_package(backup["storage_key"])
                restore_backup(
                    BytesIO(package),
                    database_name,
                    password,
                )
                result_backup_id = backup_id
                message = (
                    "Backup restored into the new database. "
                    "The active database was not changed."
                )
        _save_job_result(
            app,
            job_id,
            "successful",
            message,
            result_backup_id,
        )
    except BackupError as error:
        _save_job_result(app, job_id, "failed", error.public_message)
    except Exception as error:
        logger.error(
            "Backup job failed: operation=%s error_type=%s",
            operation,
            type(error).__name__,
        )
        _save_job_result(
            app,
            job_id,
            "failed",
            "The backup service could not complete the operation. Please try again.",
        )


def _queue_job(operation, created_by, password="", backup_id=None, database_name=None):
    app = current_app._get_current_object()
    with _job_queue_lock:
        active_job = db.session.execute(
            select(DatabaseBackupJob.id)
            .where(DatabaseBackupJob.status.in_(("queued", "running")))
            .limit(1)
        ).scalar_one_or_none()
        if active_job:
            raise BackupError(
                "Another backup operation is in progress. Wait for it to finish."
            )
        job = DatabaseBackupJob(
            id=uuid.uuid4().hex,
            operation=operation,
            status="queued",
            created_by=created_by,
            backup_id=backup_id,
            destination_database=database_name,
            message="Waiting for the backup worker.",
        )
        try:
            db.session.add(job)
            db.session.commit()
        except SQLAlchemyError as error:
            db.session.rollback()
            logger.error("Could not queue backup job: error_type=%s", type(error).__name__)
            raise BackupError("The backup operation could not be queued.") from error

        try:
            current_app.extensions["backup_executor"].submit(
                _execute_job,
                app,
                job.id,
                operation,
                created_by,
                password,
                backup_id,
                database_name,
            )
        except RuntimeError as error:
            _save_job_result(
                app,
                job.id,
                "failed",
                "The backup worker is shutting down. Please try again.",
            )
            raise BackupError("The backup worker is unavailable. Please try again.") from error
        return job


def create_worker_app(test_config=None):
    app = Flask("backup_worker")
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        BACKUP_STORAGE_BACKEND="supabase",
        BACKUP_WORKER_TOKEN=os.getenv("BACKUP_WORKER_TOKEN"),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("TESTING"):
        required = (
            "SECRET_KEY",
            "SQLALCHEMY_DATABASE_URI",
            "BACKUP_WORKER_TOKEN",
        )
        if any(not app.config.get(key) for key in required):
            raise RuntimeError("Backup worker environment is incomplete.")
        if not (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_SECRET_KEY")
        ) or not os.getenv("SUPABASE_URL"):
            raise RuntimeError("Supabase Storage environment is incomplete.")
    db.init_app(app)
    app.extensions["backup_executor"] = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="ems-backup",
    )

    @app.get("/healthz")
    def health():
        return jsonify({"status": "ok"})

    @app.before_request
    def authenticate_internal_request():
        if not request.path.startswith("/internal/v1/"):
            return None
        expected = current_app.config.get("BACKUP_WORKER_TOKEN") or ""
        authorization = request.headers.get("Authorization", "")
        supplied = authorization.removeprefix("Bearer ")
        if not expected or not hmac.compare_digest(supplied, expected):
            return jsonify({"error": "Authentication required."}), 401
        return None

    @app.errorhandler(BackupError)
    def handle_backup_error(error):
        return jsonify({"error": error.public_message}), 400

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        logger.error(
            "Unhandled backup worker request failure: error_type=%s",
            type(error).__name__,
        )
        return jsonify(
            {"error": "The backup service could not complete the request."}
        ), 500

    @app.get("/internal/v1/overview")
    def overview():
        return jsonify(backup_overview())

    @app.get("/internal/v1/backups")
    def backups():
        return jsonify({"backups": list_backups(limit=200)})

    @app.get("/internal/v1/backups/<backup_id>")
    def backup_detail(backup_id):
        backup = get_backup(backup_id)
        if backup is None:
            abort(404)
        return jsonify({"backup": backup})

    @app.get("/internal/v1/backups/<backup_id>/download-url")
    def backup_download_url(backup_id):
        backup = get_backup(backup_id)
        if backup is None or not backup.get("storage_key"):
            abort(404)
        try:
            result = _backup_storage_bucket().create_signed_url(
                backup["storage_key"],
                60,
            )
        except Exception as error:
            logger.error(
                "Could not create private backup download link: error_type=%s",
                type(error).__name__,
            )
            raise BackupError(
                "The private backup download link could not be created."
            ) from error
        signed_url = result.get("signedURL") or result.get("signedUrl")
        if not isinstance(signed_url, str) or not signed_url:
            raise BackupError(
                "The private backup download link could not be created."
            )
        signed_url = urljoin(
            os.getenv("SUPABASE_URL", "").rstrip("/") + "/",
            signed_url,
        )
        return jsonify({"backup": backup, "url": signed_url, "expires_in": 60})

    @app.delete("/internal/v1/backups/<backup_id>")
    def backup_delete(backup_id):
        if not delete_backup(backup_id):
            abort(404)
        return jsonify({"deleted": True})

    @app.post("/internal/v1/jobs/create")
    def queue_create():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Invalid backup request."}), 400
        created_by = payload.get("created_by")
        password = payload.get("password", "")
        if (
            not isinstance(created_by, str)
            or not created_by.strip()
            or len(created_by) > 100
            or not isinstance(password, str)
            or len(password) > 1024
            or (password and len(password) < 12)
        ):
            return jsonify({"error": "Invalid backup request."}), 400
        job = _queue_job("create", created_by.strip(), password)
        return jsonify({"job": _job_data(job)}), 202

    @app.post("/internal/v1/jobs/restore")
    def queue_restore():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Invalid restore request."}), 400
        backup_id = payload.get("backup_id")
        database_name = payload.get("database_name")
        password = payload.get("password", "")
        created_by = payload.get("created_by", "administrator")
        if (
            not isinstance(backup_id, str)
            or not isinstance(database_name, str)
            or not isinstance(password, str)
            or not isinstance(created_by, str)
            or not created_by.strip()
            or len(created_by) > 100
            or len(password) > 1024
        ):
            return jsonify({"error": "Invalid restore request."}), 400
        backup = get_backup(backup_id)
        if backup is None or backup.get("status") != "successful":
            abort(404)
        job = _queue_job(
            "restore",
            created_by.strip(),
            password,
            backup_id,
            database_name.strip(),
        )
        return jsonify({"job": _job_data(job)}), 202

    @app.get("/internal/v1/jobs")
    def jobs():
        try:
            records = db.session.execute(
                select(DatabaseBackupJob)
                .order_by(DatabaseBackupJob.created_at.desc())
                .limit(30)
            ).scalars()
            return jsonify({"jobs": [_job_data(job) for job in records]})
        except SQLAlchemyError as error:
            db.session.rollback()
            logger.error("Could not list backup jobs: error_type=%s", type(error).__name__)
            raise BackupError("Backup job information is temporarily unavailable.") from error

    @app.get("/internal/v1/jobs/<job_id>")
    def job_detail(job_id):
        job = db.session.get(DatabaseBackupJob, job_id)
        if job is None:
            abort(404)
        if job.status not in JOB_STATUSES:
            raise BackupError("The backup job status is invalid.")
        return jsonify({"job": _job_data(job)})

    if not app.config.get("TESTING"):
        with app.app_context():
            try:
                interrupted_jobs = db.session.execute(
                    select(DatabaseBackupJob).where(
                        DatabaseBackupJob.status.in_(("queued", "running"))
                    )
                ).scalars().all()
                for job in interrupted_jobs:
                    job.status = "failed"
                    job.message = (
                        "The worker restarted before confirming this operation. "
                        "Check backup history or the destination database before retrying."
                    )
                    job.updated_at = datetime.now(timezone.utc)
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                raise

    return app


app = create_worker_app()
