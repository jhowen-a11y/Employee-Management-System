import os
import unittest
from unittest.mock import patch

from flask import Flask

from services.database_backups import BackupError
from services.record_recovery import (
    new_staging_database_name,
    staging_maintenance_url,
    staging_target_url,
)


class RecoveryTargetTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {
            "PGHOSTADDR": "", "PGSERVICE": "", "PGSERVICEFILE": "", "PGOPTIONS": "",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.app = Flask(__name__)
        self.active = "postgresql+psycopg://active:example@remote.example/ems"
        self.local = "postgresql+psycopg://staging:example@127.0.0.1:5432/postgres"
        self.app.config.update(
            SQLALCHEMY_DATABASE_URI=self.active,
            RECOVERY_STAGING_DATABASE_URL=self.local,
        )
        context = self.app.app_context()
        context.push()
        self.addCleanup(context.pop)

    def test_explicit_local_setting_never_replaces_active_bind(self):
        target = staging_target_url(new_staging_database_name())
        self.assertEqual(target.host, "127.0.0.1")
        self.assertEqual(target.port, 5432)
        self.assertTrue(target.database.startswith("ems_recovery_"))
        self.assertEqual(self.app.config["SQLALCHEMY_DATABASE_URI"], self.active)

    def test_missing_setting_has_no_active_database_fallback(self):
        self.app.config["RECOVERY_STAGING_DATABASE_URL"] = None
        with self.assertRaisesRegex(BackupError, "not configured"):
            staging_maintenance_url()

    def test_unsafe_settings_fail_without_connecting(self):
        unsafe = [
            self.active, "invalid", "sqlite://", 42,
            "postgresql+psycopg://user@/postgres",
            "postgresql+psycopg://user@db.example/postgres",
            "postgresql+psycopg://user@127.0.0.2/postgres",
            "postgresql+psycopg://user@127.0.0.1/ems",
            "postgresql+psycopg://127.0.0.1/postgres",
            "postgresql+psycopg://user@127.0.0.1:99999/postgres",
            "postgresql+psycopg://user@127.0.0.1:0/postgres",
            "postgresql+psycopg://user@127.0.0.1/postgres?host=remote.example",
            "postgresql+psycopg://user@127.0.0.1/postgres?service=other",
            "postgresql://user@localhost/postgres",
        ]
        with patch("sqlalchemy.create_engine") as connect:
            for value in unsafe:
                with self.subTest(value=unsafe.index(value)):
                    self.app.config["RECOVERY_STAGING_DATABASE_URL"] = value
                    with self.assertRaises(BackupError) as error:
                        staging_maintenance_url()
                    self.assertNotIn("example@", str(error.exception))
            connect.assert_not_called()

    def test_local_active_server_is_rejected_across_loopback_aliases(self):
        for host in ("localhost", "127.0.0.1", "::1"):
            address = "[::1]" if host == "::1" else host
            self.app.config["SQLALCHEMY_DATABASE_URI"] = (
                f"postgresql+psycopg://active@{address}/ems"
            )
            with self.assertRaises(BackupError):
                staging_maintenance_url()

    def test_localhost_is_pinned_to_numeric_loopback(self):
        self.app.config["RECOVERY_STAGING_DATABASE_URL"] = self.local.replace(
            "127.0.0.1", "localhost"
        )
        self.assertEqual(staging_maintenance_url().host, "127.0.0.1")

    def test_only_generated_database_names_are_accepted(self):
        for name in ("postgres", "ems", "template1", "../ems", "ems_recovery_x", None,
                     "ems_recovery_" + "a" * 32 + '\n'):
            with self.subTest(name=name), self.assertRaises(BackupError):
                staging_target_url(name)

    def test_active_name_rejected_even_on_separate_server(self):
        name = new_staging_database_name()
        self.app.config["SQLALCHEMY_DATABASE_URI"] = self.active.rsplit("/", 1)[0] + "/" + name
        with self.assertRaises(BackupError):
            staging_target_url(name)

    def test_generated_names_are_unique(self):
        self.assertEqual(len({new_staging_database_name() for _ in range(100)}), 100)

    def test_libpq_environment_overrides_are_rejected(self):
        for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
            with self.subTest(key=key), patch.dict(os.environ, {key: "override"}):
                with self.assertRaises(BackupError):
                    staging_maintenance_url()
