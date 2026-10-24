import os
import unittest
from io import BytesIO
from unittest.mock import Mock, patch

from flask import Flask
from flask_login import LoginManager, UserMixin, login_user
from PIL import Image
from werkzeug.datastructures import FileStorage

import profile_storage
from profile_storage import ProfileStorageError


class ProfileStorageTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "test-secret",
                "SUPABASE_PROFILE_BUCKET": "employee-photos",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    @patch("profile_storage._storage_bucket")
    def test_profile_picture_url_uses_signed_url_for_private_bucket(self, storage):
        storage.return_value.create_signed_urls.return_value = [
            {"signedURL": "https://example.supabase.co/signed/photo.jpg"}
        ]
        app = Flask(__name__)
        with app.app_context():
            self.assertEqual(
                profile_storage.profile_picture_url("employee_1_photo.jpg"),
                "https://example.supabase.co/signed/photo.jpg",
            )
        storage.return_value.create_signed_urls.assert_called_once_with(
            ["employee_1_photo.jpg"],
            expires_in=3600,
        )

    @patch("profile_storage._storage_bucket")
    def test_profile_picture_urls_sign_multiple_pictures_in_one_request(
        self,
        storage,
    ):
        storage.return_value.create_signed_urls.return_value = [
            {"signedURL": "https://example.test/one"},
            {"signedURL": "https://example.test/two"},
        ]

        with Flask(__name__).app_context():
            urls = profile_storage.profile_picture_urls(
                ["one.jpg", "two.jpg", "one.jpg"]
            )

        self.assertEqual(
            urls,
            {
                "one.jpg": "https://example.test/one",
                "two.jpg": "https://example.test/two",
            },
        )
        storage.return_value.create_signed_urls.assert_called_once_with(
            ["one.jpg", "two.jpg"],
            expires_in=3600,
        )

    @patch("profile_storage._storage_bucket")
    def test_signed_url_cache_is_scoped_to_user_and_role(
        self,
        storage,
    ):
        class Account(UserMixin):
            def __init__(self, account_id, role):
                self.id = account_id
                self.role = role

        app = Flask(__name__)
        app.secret_key = "profile-storage-tests"
        login_manager = LoginManager(app)
        accounts = {
            "account-one": Account("account-one", "admin"),
            "account-one-employee": Account("account-one", "employee"),
            "account-two": Account("account-two", "admin"),
        }

        @login_manager.user_loader
        def load_user(user_id):
            return accounts.get(user_id)

        storage.return_value.create_signed_urls.return_value = [
            {"signedURL": "https://example.test/signed/photo"}
        ]
        with profile_storage._signed_url_cache_lock:
            profile_storage._signed_url_cache.clear()

        for account in (accounts["account-one"], accounts["account-one"]):
            with app.test_request_context():
                login_user(account)
                self.assertEqual(
                    profile_storage.profile_picture_url("cached-photo.jpg"),
                    "https://example.test/signed/photo",
                )

        with app.test_request_context():
            login_user(accounts["account-one-employee"])
            profile_storage.profile_picture_url("cached-photo.jpg")

        with app.test_request_context():
            login_user(accounts["account-two"])
            profile_storage.profile_picture_url("cached-photo.jpg")

        self.assertEqual(
            storage.return_value.create_signed_urls.call_count,
            3,
        )

    def test_signed_url_cache_expires_before_storage_url(self):
        cache_key = ("account", "employee", "project", "bucket", "photo.jpg")
        with profile_storage._signed_url_cache_lock:
            profile_storage._signed_url_cache.clear()
        with patch(
            "profile_storage.time.monotonic",
            side_effect=(
                100,
                100 + profile_storage.SIGNED_URL_CACHE_SECONDS + 1,
            ),
        ):
            profile_storage._store_cached_signed_url(cache_key, "signed-url")
            self.assertIsNone(
                profile_storage._get_cached_signed_url(cache_key)
            )

    def test_profile_picture_url_rejects_paths(self):
        app = Flask(__name__)
        with app.app_context():
            with self.assertRaises(ProfileStorageError):
                profile_storage.profile_picture_url("../private.jpg")

    @patch("profile_storage.create_client")
    def test_upload_uses_supabase_bucket_and_content_type(self, create_client):
        bucket = Mock()
        create_client.return_value.storage.from_.return_value = bucket

        profile_storage.upload_profile_picture(
            "employee_1_photo.png",
            b"image data",
            "image/png",
        )

        create_client.assert_called_once_with(
            "https://example.supabase.co",
            "test-secret",
        )
        create_client.return_value.storage.from_.assert_called_once_with(
            "employee-photos"
        )
        bucket.upload.assert_called_once_with(
            "employee_1_photo.png",
            b"image data",
            {"content-type": "image/png", "upsert": "false"},
        )

    @patch("profile_storage.upload_profile_picture")
    def test_upload_uses_actual_image_format(self, upload):
        image_data = BytesIO()
        Image.new("RGB", (2, 2), color="blue").save(
            image_data,
            format="PNG",
        )
        image_data.seek(0)
        upload_file = FileStorage(stream=image_data, filename="avatar.webp")

        app = Flask(__name__)
        with app.app_context():
            filename, error = profile_storage.save_profile_picture(
                upload_file,
                employee_id=1,
            )

        self.assertIsNone(error)
        self.assertTrue(filename.endswith(".png"))
        upload.assert_called_once()
        self.assertEqual(upload.call_args.args[0], filename)
        self.assertEqual(upload.call_args.args[2], "image/png")


if __name__ == "__main__":
    unittest.main()
