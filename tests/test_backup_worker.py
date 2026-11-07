import os
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

from flask import Flask

from models import db
from models.database_backup import DatabaseBackupJob
from services import backup_worker_client
from services.database_backups import BackupError


class BackupWorkerClientTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            BACKUP_WORKER_URL="https://backup-worker.example.test",
            BACKUP_WORKER_TOKEN="test-worker-token",
        )

    def test_create_request_uses_https_and_server_side_bearer_auth(self):
        response = Mock()
        response.is_success = True
        response.json.return_value = {
            "job": {
                "id": "a" * 32,
                "operation": "create",
                "status": "queued",
            }
        }
        with patch("services.backup_worker_client.httpx.Client") as client_factory:
            client = client_factory.return_value.__enter__.return_value
            client.request.return_value = response
            with self.app.app_context():
                result = backup_worker_client.create_backup(
                    "admin",
                    "very-strong-test-password",
                )

        self.assertEqual(result["status"], "queued")
        request = client.request.call_args
        self.assertEqual(request.args[0], "POST")
        self.assertEqual(
            request.args[1],
            "https://backup-worker.example.test/internal/v1/jobs/create",
        )
        self.assertEqual(
            request.kwargs["headers"]["Authorization"],
            "Bearer test-worker-token",
        )
        self.assertEqual(
            request.kwargs["json"],
            {
                "created_by": "admin",
                "password": "very-strong-test-password",
            },
        )

    def test_worker_url_must_use_https(self):
        self.app.config["BACKUP_WORKER_URL"] = "http://backup-worker.example.test"
        with self.app.app_context(), self.assertRaisesRegex(
            BackupError,
            "secure HTTPS",
        ):
            backup_worker_client.create_backup("admin")

    def test_vercel_never_falls_back_to_local_backup_storage(self):
        self.app.config["BACKUP_WORKER_URL"] = None
        with patch.dict(os.environ, {"VERCEL": "1"}):
            with self.app.app_context():
                overview = backup_worker_client.backup_overview()
                self.assertTrue(overview["worker_mode"])
                self.assertFalse(overview["backup_service_available"])
                self.assertEqual(overview["storage_backend"], "supabase")

    def test_worker_internal_endpoints_reject_missing_bearer_token(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_url = "sqlite:///" + os.path.join(
                temporary_directory,
                "worker-test.sqlite",
            )
            bootstrap = Flask("backup-worker-test-bootstrap")
            bootstrap.config["SQLALCHEMY_DATABASE_URI"] = database_url
            db.init_app(bootstrap)
            with bootstrap.app_context():
                db.create_all()
            with patch.dict(
                os.environ,
                {
                    "DATABASE_URL": database_url,
                    "SECRET_KEY": "worker-test-secret",
                    "BACKUP_WORKER_TOKEN": "worker-test-token",
                    "SUPABASE_URL": "https://example.supabase.co",
                    "SUPABASE_SECRET_KEY": "not-a-real-secret",
                },
            ):
                from backup_worker.app import app as production_app
                from backup_worker.app import create_worker_app

                app = create_worker_app(
                    {
                        "TESTING": True,
                        "SECRET_KEY": "worker-test-secret",
                        "SQLALCHEMY_DATABASE_URI": database_url,
                        "BACKUP_WORKER_TOKEN": "worker-test-token",
                    }
                )
            try:
                client = app.test_client()
                self.assertEqual(client.get("/healthz").status_code, 200)
                self.assertEqual(
                    client.get("/internal/v1/backups").status_code,
                    401,
                )
                self.assertEqual(
                    client.get(
                        "/internal/v1/backups",
                        headers={"Authorization": "Bearer wrong-token"},
                    ).status_code,
                    401,
                )
            finally:
                app.extensions["backup_executor"].shutdown(wait=False)
                production_app.extensions["backup_executor"].shutdown(wait=False)
                with app.app_context():
                    db.engine.dispose()
                with production_app.app_context():
                    db.engine.dispose()
                with bootstrap.app_context():
                    db.engine.dispose()

    def _create_worker_app_with_sqlite(self):
        temporary_directory = tempfile.TemporaryDirectory()
        database_url = "sqlite:///" + os.path.join(
            temporary_directory.name,
            "worker-exec-test.sqlite",
        )
        bootstrap = Flask("backup-worker-test-bootstrap")
        bootstrap.config["SQLALCHEMY_DATABASE_URI"] = database_url
        db.init_app(bootstrap)
        with bootstrap.app_context():
            db.create_all()
            db.engine.dispose()
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": database_url,
                "SECRET_KEY": "worker-test-secret",
                "BACKUP_WORKER_TOKEN": "worker-test-token",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SECRET_KEY": "not-a-real-secret",
            },
        ):
            from backup_worker.app import create_worker_app

            app = create_worker_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": "worker-test-secret",
                    "SQLALCHEMY_DATABASE_URI": database_url,
                    "BACKUP_WORKER_TOKEN": "worker-test-token",
                }
            )
        with app.app_context():
            db.engine.dispose()
        return app, temporary_directory

    def test_successful_backup_job_execution(self):
        app, temp_dir = self._create_worker_app_with_sqlite()
        try:
            with app.app_context():
                job = DatabaseBackupJob(
                    id=uuid.uuid4().hex,
                    operation="create",
                    status="queued",
                    created_by="admin",
                    message="Waiting for the backup worker.",
                )
                db.session.add(job)
                db.session.commit()
                job_id = job.id

            from backup_worker.app import _execute_job

            with patch(
                "backup_worker.app.create_backup",
                return_value={"id": "backup-123"},
            ) as mock_create:
                _execute_job(app, job_id, "create", "admin", None, None, None)

            with app.app_context():
                updated = db.session.get(DatabaseBackupJob, job_id)
                self.assertEqual(updated.status, "successful")
                self.assertEqual(updated.message, "Backup created and verified.")
                self.assertEqual(updated.backup_id, "backup-123")
            mock_create.assert_called_once_with("admin", None)
        finally:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
            shutil.rmtree(temp_dir.name, ignore_errors=True)

    def test_backup_job_fails_on_backup_error(self):
        app, temp_dir = self._create_worker_app_with_sqlite()
        try:
            with app.app_context():
                job = DatabaseBackupJob(
                    id=uuid.uuid4().hex,
                    operation="create",
                    status="queued",
                    created_by="admin",
                    message="Waiting for the backup worker.",
                )
                db.session.add(job)
                db.session.commit()
                job_id = job.id

            from backup_worker.app import _execute_job

            error = BackupError("Disk is full.")
            with patch("backup_worker.app.create_backup", side_effect=error):
                _execute_job(app, job_id, "create", "admin", None, None, None)

            with app.app_context():
                updated = db.session.get(DatabaseBackupJob, job_id)
                self.assertEqual(updated.status, "failed")
                self.assertEqual(updated.message, "Disk is full.")
        finally:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
            shutil.rmtree(temp_dir.name, ignore_errors=True)

    def test_backup_job_fails_on_unexpected_exception(self):
        app, temp_dir = self._create_worker_app_with_sqlite()
        try:
            with app.app_context():
                job = DatabaseBackupJob(
                    id=uuid.uuid4().hex,
                    operation="create",
                    status="queued",
                    created_by="admin",
                    message="Waiting for the backup worker.",
                )
                db.session.add(job)
                db.session.commit()
                job_id = job.id

            from backup_worker.app import _execute_job

            with patch(
                "backup_worker.app.create_backup",
                side_effect=RuntimeError("unexpected"),
            ):
                _execute_job(app, job_id, "create", "admin", None, None, None)

            with app.app_context():
                updated = db.session.get(DatabaseBackupJob, job_id)
                self.assertEqual(updated.status, "failed")
                self.assertEqual(
                    updated.message,
                    "The backup service could not complete the operation. Please try again.",
                )
        finally:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
            shutil.rmtree(temp_dir.name, ignore_errors=True)

    def test_successful_restore_job_execution(self):
        app, temp_dir = self._create_worker_app_with_sqlite()
        try:
            with app.app_context():
                job = DatabaseBackupJob(
                    id=uuid.uuid4().hex,
                    operation="restore",
                    status="queued",
                    created_by="admin",
                    backup_id="backup-456",
                    destination_database="ems_restore_test",
                    message="Waiting for the backup worker.",
                )
                db.session.add(job)
                db.session.commit()
                job_id = job.id

            from backup_worker.app import _execute_job

            with patch(
                "backup_worker.app.get_backup",
                return_value={
                    "id": "backup-456",
                    "status": "successful",
                    "storage_key": "ems/backup-456.emsbackup",
                },
            ), patch(
                "backup_worker.app._download_package",
                return_value=b"package-bytes",
            ), patch(
                "backup_worker.app.restore_backup",
                return_value="ems_restore_test",
            ):
                _execute_job(
                    app,
                    job_id,
                    "restore",
                    "admin",
                    "",
                    "backup-456",
                    "ems_restore_test",
                )

            with app.app_context():
                updated = db.session.get(DatabaseBackupJob, job_id)
                self.assertEqual(updated.status, "successful")
                self.assertEqual(updated.backup_id, "backup-456")
                self.assertIn("restored into the new database", updated.message)
        finally:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
            shutil.rmtree(temp_dir.name, ignore_errors=True)

    def test_restore_job_fails_when_backup_unavailable(self):
        app, temp_dir = self._create_worker_app_with_sqlite()
        try:
            with app.app_context():
                job = DatabaseBackupJob(
                    id=uuid.uuid4().hex,
                    operation="restore",
                    status="queued",
                    created_by="admin",
                    backup_id="backup-789",
                    destination_database="ems_restore_test",
                    message="Waiting for the backup worker.",
                )
                db.session.add(job)
                db.session.commit()
                job_id = job.id

            from backup_worker.app import _execute_job

            with patch("backup_worker.app.get_backup", return_value=None):
                _execute_job(
                    app,
                    job_id,
                    "restore",
                    "admin",
                    "",
                    "backup-789",
                    "ems_restore_test",
                )

            with app.app_context():
                updated = db.session.get(DatabaseBackupJob, job_id)
                self.assertEqual(updated.status, "failed")
                self.assertEqual(
                    updated.message, "The selected backup is unavailable."
                )
        finally:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
            shutil.rmtree(temp_dir.name, ignore_errors=True)

    def test_duplicate_job_prevention(self):
        app, temp_dir = self._create_worker_app_with_sqlite()
        try:
            with app.app_context():
                queued_job = DatabaseBackupJob(
                    id=uuid.uuid4().hex,
                    operation="create",
                    status="queued",
                    created_by="admin",
                    message="Waiting for the backup worker.",
                )
                db.session.add(queued_job)
                db.session.commit()

                from backup_worker.app import _queue_job

                with self.assertRaisesRegex(
                    BackupError, "Another backup operation is in progress"
                ):
                    _queue_job("create", "admin")

                queued_job.status = "successful"
                running_job = DatabaseBackupJob(
                    id=uuid.uuid4().hex,
                    operation="create",
                    status="running",
                    created_by="admin",
                    message="Operation in progress.",
                )
                db.session.add(running_job)
                db.session.commit()

                with self.assertRaisesRegex(
                    BackupError, "Another backup operation is in progress"
                ):
                    _queue_job("create", "admin")

                running_job.status = "successful"
                db.session.commit()

                with patch.object(
                    app.extensions["backup_executor"], "submit"
                ) as mock_submit:
                    job = _queue_job("create", "admin")
                    self.assertIsNotNone(job)
                    mock_submit.assert_called_once()
        finally:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
            shutil.rmtree(temp_dir.name, ignore_errors=True)

    def test_interrupted_job_recovery(self):
        temporary_directory = tempfile.TemporaryDirectory()
        database_url = "sqlite:///" + os.path.join(
            temporary_directory.name,
            "worker-recovery-test.sqlite",
        )
        bootstrap = Flask("backup-worker-test-bootstrap")
        bootstrap.config["SQLALCHEMY_DATABASE_URI"] = database_url
        db.init_app(bootstrap)
        with bootstrap.app_context():
            db.create_all()
            db.engine.dispose()

        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": database_url,
                "SECRET_KEY": "worker-test-secret",
                "BACKUP_WORKER_TOKEN": "worker-test-token",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SECRET_KEY": "not-a-real-secret",
            },
        ):
            from backup_worker.app import create_worker_app

            with bootstrap.app_context():
                job1 = DatabaseBackupJob(
                    id=uuid.uuid4().hex,
                    operation="create",
                    status="queued",
                    created_by="admin",
                    message="Waiting for the backup worker.",
                )
                job2 = DatabaseBackupJob(
                    id=uuid.uuid4().hex,
                    operation="restore",
                    status="running",
                    created_by="admin",
                    backup_id="abc123",
                    destination_database="test_db",
                    message="Operation in progress.",
                )
                db.session.add_all([job1, job2])
                db.session.commit()
                job1_id = job1.id
                job2_id = job2.id
                db.engine.dispose()

            app = create_worker_app(
                {
                    "SECRET_KEY": "worker-test-secret",
                    "SQLALCHEMY_DATABASE_URI": database_url,
                    "BACKUP_WORKER_TOKEN": "worker-test-token",
                }
            )

        try:
            with app.app_context():
                recovered_job1 = db.session.get(DatabaseBackupJob, job1_id)
                recovered_job2 = db.session.get(DatabaseBackupJob, job2_id)
                self.assertEqual(recovered_job1.status, "failed")
                self.assertEqual(recovered_job2.status, "failed")
                self.assertIn("worker restarted", recovered_job1.message)
                self.assertIn("worker restarted", recovered_job2.message)
                db.engine.dispose()
        finally:
            app.extensions["backup_executor"].shutdown(wait=False)
            shutil.rmtree(temporary_directory.name, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
