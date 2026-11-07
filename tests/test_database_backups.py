import os
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.engine import make_url
from werkzeug.security import generate_password_hash

import services.database_backups as database_backups
from models.database_backup import DatabaseBackup


class DatabaseBackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = patch.dict(
            os.environ,
            {
                "SECRET_KEY": "database-backup-test-secret",
                "DATABASE_URL": "postgresql://test:test@localhost/test",
            },
        )
        cls.environment.start()

        from app import create_app
        from models import db
        from models.user import User

        cls.db = db
        cls.User = User
        cls.app = create_app(
            {
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "SECRET_KEY": "database-backup-test-secret",
                "TESTING": True,
            }
        )
        with cls.app.app_context():
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            cls.db.session.remove()
            cls.db.drop_all()
            cls.db.engine.dispose()
        cls.environment.stop()

    def setUp(self):
        with self.app.app_context():
            self.db.drop_all()
            self.db.create_all()
            self.admin = self._add_user("admin", self.User.ADMIN)
            self.hr = self._add_user("hr", self.User.HR)
            self.employee = self._add_user("employee", self.User.EMPLOYEE)
            self.db.session.commit()
            self.user_ids = {
                self.admin.username: self.admin.id,
                self.hr.username: self.hr.id,
                self.employee.username: self.employee.id,
            }
        self.backup_directory = tempfile.TemporaryDirectory()
        self.app.config["BACKUP_DIRECTORY"] = self.backup_directory.name
        self.client = self.app.test_client()

    def tearDown(self):
        self.backup_directory.cleanup()

    def test_default_backup_directory_uses_local_user_storage(self):
        if os.name != "nt":
            self.skipTest("Windows local-user storage path")

        with tempfile.TemporaryDirectory() as local_data:
            configured = self.app.config.pop("BACKUP_DIRECTORY", None)
            try:
                with patch.dict(
                    os.environ,
                    {"EMS_BACKUP_DIRECTORY": "", "LOCALAPPDATA": local_data},
                ):
                    with self.app.app_context():
                        directory = database_backups._backup_directory()
                self.assertEqual(
                    directory,
                    Path(local_data) / "MCM-EMS" / "database-backups",
                )
            finally:
                if configured is not None:
                    self.app.config["BACKUP_DIRECTORY"] = configured

    def _add_user(self, username, role):
        user = self.User(
            username=username,
            email=f"{username}@example.test",
            password_hash=generate_password_hash("test-password"),
            role=role,
        )
        self.db.session.add(user)
        return user

    def _login(self, username):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(self.user_ids[username])
            session["_fresh"] = True
            session["_csrf_token"] = "test-csrf-token"
        return client

    def _postgres_url(self):
        return make_url("postgresql+psycopg://user:password@db.example.test/ems")

    def _mock_tool(self, arguments, _url, timeout=900):
        if "--file" in arguments:
            dump_path = Path(arguments[arguments.index("--file") + 1])
            dump_path.write_bytes(b"test PostgreSQL custom archive")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    def _create_test_backup(self, password=None):
        with patch.object(
            database_backups, "_database_url", return_value=self._postgres_url()
        ), patch.object(
            database_backups, "_utility_path", side_effect=lambda name: name
        ), patch.object(database_backups, "_run_tool", side_effect=self._mock_tool):
            return database_backups.create_backup("admin", password)

    def test_only_administrators_can_open_backup_routes(self):
        admin = self._login("admin")
        response = admin.get("/admin/database-backups")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Database Backup", response.data)
        self.assertIn(b"Create a backup", response.data)
        self.assertIn(b"Restore to a new database", response.data)

        for username in ("hr", "employee"):
            client = self._login(username)
            self.assertEqual(
                client.get("/admin/database-backups").status_code,
                403,
            )
            self.assertEqual(
                client.post(
                    "/admin/database-backups/create",
                    data={"_csrf_token": "test-csrf-token"},
                ).status_code,
                403,
            )
            self.assertNotIn(b"Database Backup", client.get("/").data)

    def test_creation_history_and_download_use_private_storage(self):
        with self.app.app_context():
            backup = self._create_test_backup()
            self.assertEqual(backup["status"], "successful")
            self.assertTrue(Path(backup["filename"]).name == backup["filename"])
            self.assertEqual(
                Path(self.backup_directory.name, backup["filename"]).parent,
                Path(self.backup_directory.name),
            )

        admin = self._login("admin")
        page = admin.get("/admin/database-backups")
        self.assertIn(backup["filename"].encode(), page.data)
        self.assertIn(b"Available backups", page.data)
        download = admin.get(
            f"/admin/database-backups/{backup['id']}/download"
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(
            download.headers["Content-Disposition"].split(";")[0],
            "attachment",
        )
        self.assertEqual(download.headers["Cache-Control"], "private, no-store")
        download.close()

        for username in ("hr", "employee"):
            self.assertEqual(
                self._login(username).get(
                    f"/admin/database-backups/{backup['id']}/download"
                ).status_code,
                403,
            )

    def test_encrypted_package_authenticates_before_creating_destination(self):
        with self.app.app_context():
            backup = self._create_test_backup("very-strong-test-password")
            package_path = Path(self.backup_directory.name, backup["filename"])

            with patch.object(
                database_backups, "_database_url", return_value=self._postgres_url()
            ), patch.object(
                database_backups, "_create_destination_database"
            ) as create_database:
                with package_path.open("rb") as package:
                    with self.assertRaises(database_backups.BackupError):
                        database_backups.restore_backup(
                            package,
                            "ems_restore_test",
                            "incorrect-password",
                        )
                create_database.assert_not_called()

                with patch.object(
                    database_backups,
                    "_utility_path",
                    side_effect=lambda name: name,
                ), patch.object(
                    database_backups,
                    "_run_tool",
                    return_value=SimpleNamespace(
                        returncode=0,
                        stdout=b"",
                        stderr=b"",
                    ),
                ) as run_tool:
                    with package_path.open("rb") as package:
                        destination = database_backups.restore_backup(
                            package,
                            "ems_restore_test",
                            "very-strong-test-password",
                        )
                self.assertEqual(destination, "ems_restore_test")
                create_database.assert_called_once()
                self.assertIn("--single-transaction", run_tool.call_args_list[-1].args[0])

    def test_invalid_upload_is_rejected_without_database_changes(self):
        with self.app.app_context():
            with patch.object(
                database_backups, "_database_url", return_value=self._postgres_url()
            ), patch.object(
                database_backups, "_create_destination_database"
            ) as create_database:
                with self.assertRaisesRegex(
                    database_backups.BackupError, "uploaded backup file is invalid"
                ):
                    database_backups.restore_backup(
                        BytesIO(b"not a backup"),
                        "ems_restore_test",
                    )
                create_database.assert_not_called()

    def test_restore_refuses_active_or_unsafe_database_names(self):
        with self.app.app_context():
            with patch.object(
                database_backups, "_database_url", return_value=self._postgres_url()
            ):
                for database_name in ("ems", "../postgres", "template1", "bad-name"):
                    with self.subTest(database_name=database_name):
                        with self.assertRaises(database_backups.BackupError):
                            database_backups.restore_backup(
                                BytesIO(b"not read"),
                                database_name,
                            )

    def test_restore_requires_confirmation_in_the_admin_form(self):
        client = self._login("admin")
        response = client.post(
            "/admin/database-backups/restore",
            data={
                "_csrf_token": "test-csrf-token",
                "confirm_overwrite": "on",
                "restore_database_name": "ems_restore_test",
            },
        )
        self.assertEqual(response.status_code, 302)
        follow_up = client.get(response.location)
        self.assertIn(b"Confirm the restore in the confirmation dialog", follow_up.data)
        self.assertEqual(
            list(Path(self.backup_directory.name).glob("*.emsbackup")),
            [],
        )

    def test_oversized_restore_upload_has_a_safe_error_response(self):
        previous_limit = self.app.config["BACKUP_UPLOAD_MAX_CONTENT_LENGTH"]
        self.app.config["BACKUP_UPLOAD_MAX_CONTENT_LENGTH"] = 128
        try:
            response = self._login("admin").post(
                "/admin/database-backups/restore",
                data={
                    "_csrf_token": "test-csrf-token",
                    "backup_file": (BytesIO(b"x" * 512), "large.emsbackup"),
                },
                content_type="multipart/form-data",
            )
        finally:
            self.app.config["BACKUP_UPLOAD_MAX_CONTENT_LENGTH"] = previous_limit
        self.assertEqual(response.status_code, 413)
        self.assertIn(b"uploaded backup file exceeds the 512 MB size limit", response.data)

    def test_failed_backup_is_recorded_as_failed_not_successful(self):
        with self.app.app_context():
            with patch.object(
                database_backups,
                "_database_url",
                return_value=self._postgres_url(),
            ), patch.object(
                database_backups,
                "_utility_path",
                side_effect=lambda name: name,
            ), patch.object(
                database_backups,
                "_run_tool",
                side_effect=database_backups.BackupError("safe failure"),
            ):
                with self.assertRaises(database_backups.BackupError):
                    database_backups.create_backup("admin")
            backups = database_backups.list_backups()
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0]["status"], "failed")

    def test_failed_restore_removes_new_destination_database(self):
        with self.app.app_context():
            backup = self._create_test_backup()
            package_path = Path(self.backup_directory.name, backup["filename"])

            def fail_restore(arguments, _url, timeout=900):
                if "--list" in arguments:
                    return SimpleNamespace(
                        returncode=0,
                        stdout=b"",
                        stderr=b"",
                    )
                raise database_backups.BackupError("safe test failure")

            with patch.object(
                database_backups, "_database_url", return_value=self._postgres_url()
            ), patch.object(
                database_backups, "_utility_path", side_effect=lambda name: name
            ), patch.object(
                database_backups, "_create_destination_database"
            ) as create_database, patch.object(
                database_backups, "_drop_destination_database"
            ) as drop_database, patch.object(
                database_backups, "_run_tool", side_effect=fail_restore
            ):
                with package_path.open("rb") as package:
                    with self.assertRaisesRegex(
                        database_backups.BackupError,
                        "active database has not been changed",
                    ):
                        database_backups.restore_backup(
                            package,
                            "ems_restore_test",
                        )
                create_database.assert_called_once()
                drop_database.assert_called_once_with(
                    self._postgres_url(),
                    "ems_restore_test",
                )

    def test_package_is_signed_and_contains_only_supported_archive(self):
        with self.app.app_context():
            backup = self._create_test_backup()
            path = Path(self.backup_directory.name, backup["filename"])
            with zipfile.ZipFile(path) as package:
                self.assertEqual(
                    set(package.namelist()),
                    {"manifest.json", "backup.dump"},
                )
                manifest, payload_name = database_backups._read_manifest(path)
                self.assertEqual(manifest["format"], "mcm-ems-postgresql")
                self.assertEqual(payload_name, "backup.dump")

                changed_manifest = dict(manifest, version=999)
                package_data = BytesIO()
                with zipfile.ZipFile(package_data, "w") as changed:
                    changed.writestr(
                        "manifest.json",
                        database_backups._canonical_json(changed_manifest),
                    )
                    changed.writestr("backup.dump", b"test archive")
                with tempfile.NamedTemporaryFile(suffix=".emsbackup") as changed_file:
                    changed_file.write(package_data.getvalue())
                    changed_file.flush()
                    with self.assertRaises(database_backups.BackupError):
                        database_backups._read_manifest(Path(changed_file.name))

    def test_postgres_credentials_are_passed_through_private_passfile(self):
        with self.app.app_context():
            url = make_url(
                "postgresql+psycopg://user:p%3Aa%5Css@db.example.test/ems"
            )
            environment, passfile = database_backups._tool_environment(url)
            try:
                self.assertNotIn("PGPASSWORD", environment)
                self.assertEqual(environment["PGUSER"], "user")
                self.assertNotIn("p:a", str(environment))
                self.assertEqual(
                    passfile.read_text(encoding="utf-8"),
                    "db.example.test:*:ems:user:p\\:a\\\\ss\n",
                )
                if os.name != "nt":
                    self.assertEqual(passfile.stat().st_mode & 0o777, 0o600)
            finally:
                passfile.unlink(missing_ok=True)

    def test_supabase_backend_uploads_package_and_persists_metadata_in_database(self):
        previous_backend = self.app.config.get("BACKUP_STORAGE_BACKEND")
        self.app.config["BACKUP_STORAGE_BACKEND"] = "supabase"
        try:
            uploaded_sizes = []

            def capture_upload(path, _storage_key):
                uploaded_sizes.append(path.stat().st_size)

            with self.app.app_context(), patch.object(
                database_backups,
                "_upload_package",
                side_effect=capture_upload,
            ) as upload:
                backup = self._create_test_backup()
                self.assertEqual(backup["status"], "successful")
                self.assertTrue(backup["verified"])
                self.assertEqual(
                    backup["storage_key"],
                    f"ems/{backup['id']}.emsbackup",
                )
                self.assertEqual(backup["file_size"], uploaded_sizes[0])
                upload.assert_called_once()
                self.assertEqual(
                    database_backups.list_backups()[0]["id"],
                    backup["id"],
                )
                self.assertIsNotNone(
                    self.db.session.get(DatabaseBackup, backup["id"])
                )
                self.assertFalse(
                    Path(self.backup_directory.name, backup["filename"]).exists()
                )
        finally:
            if previous_backend is None:
                self.app.config.pop("BACKUP_STORAGE_BACKEND", None)
            else:
                self.app.config["BACKUP_STORAGE_BACKEND"] = previous_backend

    def test_supabase_backend_rejects_oversize_final_package_before_upload(self):
        previous_backend = self.app.config.get("BACKUP_STORAGE_BACKEND")
        self.app.config["BACKUP_STORAGE_BACKEND"] = "supabase"
        try:
            def write_oversize_package(_dump_path, package_path, _password):
                package_path.write_bytes(b"x" * 101)

            with self.app.app_context(), patch.object(
                database_backups,
                "MAX_REMOTE_PACKAGE_SIZE",
                100,
            ), patch.object(
                database_backups,
                "_write_package",
                side_effect=write_oversize_package,
            ), patch.object(
                database_backups,
                "_upload_package",
            ) as upload, patch.object(
                database_backups,
                "_delete_package",
            ) as delete_object, patch.object(
                database_backups,
                "_database_url",
                return_value=self._postgres_url(),
            ), patch.object(
                database_backups,
                "_utility_path",
                side_effect=lambda name: name,
            ), patch.object(
                database_backups,
                "_run_tool",
                side_effect=self._mock_tool,
            ):
                with self.assertRaisesRegex(
                    database_backups.BackupError,
                    "final backup package exceeds the 50 MB",
                ):
                    database_backups.create_backup("admin")
                upload.assert_not_called()
                delete_object.assert_not_called()
                self.assertEqual(database_backups.list_backups()[0]["status"], "failed")
        finally:
            if previous_backend is None:
                self.app.config.pop("BACKUP_STORAGE_BACKEND", None)
            else:
                self.app.config["BACKUP_STORAGE_BACKEND"] = previous_backend

    def test_supabase_deletion_removes_object_and_database_metadata(self):
        previous_backend = self.app.config.get("BACKUP_STORAGE_BACKEND")
        self.app.config["BACKUP_STORAGE_BACKEND"] = "supabase"
        try:
            with self.app.app_context(), patch.object(
                database_backups,
                "_upload_package",
            ), patch.object(
                database_backups,
                "_delete_package",
            ) as delete_object:
                backup = self._create_test_backup()
                self.assertTrue(database_backups.delete_backup(backup["id"]))
                delete_object.assert_called_once_with(backup["storage_key"])
                self.assertIsNone(
                    self.db.session.get(DatabaseBackup, backup["id"])
                )
        finally:
            if previous_backend is None:
                self.app.config.pop("BACKUP_STORAGE_BACKEND", None)
            else:
                self.app.config["BACKUP_STORAGE_BACKEND"] = previous_backend
