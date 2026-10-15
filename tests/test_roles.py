import os
import re
import unittest
from unittest.mock import patch

from werkzeug.security import check_password_hash, generate_password_hash


class RoleManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = patch.dict(
            os.environ,
            {
                "SECRET_KEY": "role-tests-only",
                "DB_USER": "test",
                "DB_PASSWORD": "test",
                "DB_HOST": "localhost",
                "DB_NAME": "test",
                "DB_PORT": "5432",
            },
        )
        cls.environment.start()

        from app import create_app
        from models import db
        from models.user import User

        cls.db = db
        cls.User = User
        cls.app = create_app(
            {"SQLALCHEMY_DATABASE_URI": "sqlite://", "TESTING": True}
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
            self.admin = self.User(
                username="admin",
                email="admin@example.test",
                password_hash=generate_password_hash("AdminPass123"),
                role=self.User.ADMIN,
            )
            self.employee = self.User(
                username="staff",
                email="staff@example.test",
                password_hash=generate_password_hash("StaffPass123"),
                role=self.User.EMPLOYEE,
            )
            self.hr = self.User(
                username="hrstaff",
                email="hrstaff@example.test",
                password_hash=generate_password_hash("HrPass123"),
                role=self.User.HR,
            )
            self.db.session.add_all([self.admin, self.employee, self.hr])
            self.db.session.commit()
            self.admin_id = self.admin.id

        self.client = self.app.test_client()

    @staticmethod
    def csrf_token(response):
        match = re.search(
            r'name="_csrf_token" value="([^"]+)"',
            response.get_data(as_text=True),
        )
        if match is None:
            raise AssertionError("Form did not include a CSRF token.")
        return match.group(1)

    def login(self, client, username, password, path="/login"):
        response = client.get(path)
        return client.post(
            path,
            data={
                "_csrf_token": self.csrf_token(response),
                "username": username,
                "password": password,
            },
        )

    def test_login_required_and_admin_can_manage_accounts(self):
        self.assertEqual(self.client.get("/users/").status_code, 302)
        self.assertEqual(
            self.login(self.client, "admin", "AdminPass123").status_code,
            302,
        )

        add_response = self.client.get("/users/add")
        response = self.client.post(
            "/users/add",
            data={
                "_csrf_token": self.csrf_token(add_response),
                "username": "hruser",
                "email": "hr@example.test",
                "password": "HrPass123",
                "role": self.User.HR,
            },
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            hr_user = self.User.query.filter_by(username="hruser").one()
            self.assertEqual(hr_user.role, self.User.HR)
            self.assertTrue(
                check_password_hash(hr_user.password_hash, "HrPass123")
            )
            hr_user_id = hr_user.id

        listing = self.client.get("/users/")
        response = self.client.post(
            f"/users/{hr_user_id}/role",
            data={
                "_csrf_token": self.csrf_token(listing),
                "role": self.User.EMPLOYEE,
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(self.User, hr_user_id).role,
                self.User.EMPLOYEE,
            )

    def test_create_admin_cli_provisions_first_account(self):
        with self.app.app_context():
            self.db.drop_all()
            self.db.create_all()

        result = self.app.test_cli_runner().invoke(
            args=["create-admin"],
            input=(
                "firstadmin\nadmin@example.test\n"
                "AdminPass123\nAdminPass123\n"
            ),
        )
        self.assertEqual(result.exit_code, 0, result.output)
        with self.app.app_context():
            admin = self.User.query.filter_by(username="firstadmin").one()
            self.assertEqual(admin.role, self.User.ADMIN)
            self.assertTrue(
                check_password_hash(admin.password_hash, "AdminPass123")
            )

    def test_non_admin_cannot_manage_users_or_create_accounts(self):
        response = self.login(self.client, "staff", "StaffPass123")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/employee/home")
        home = self.client.get(response.location)
        self.assertEqual(home.status_code, 200)
        self.assertIn(
            b"Employee portal coming soon",
            home.get_data(),
        )
        self.assertEqual(self.client.get("/").location, "/employee/home")
        self.assertEqual(self.client.get("/users/").status_code, 403)
        self.assertEqual(self.client.get("/employees/add").status_code, 403)

    def test_admin_login_stays_on_shared_dashboard(self):
        response = self.login(self.client, "admin", "AdminPass123")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/")

    def test_hr_login_uses_hr_home_placeholder(self):
        response = self.login(self.client, "hrstaff", "HrPass123")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/hr/home")
        home = self.client.get(response.location)
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"HR portal coming soon", home.get_data())
        self.assertEqual(self.client.get("/").location, "/hr/home")
        self.assertEqual(self.client.get("/employee/home").status_code, 403)

    def test_role_change_requires_csrf_and_cannot_demote_current_admin(self):
        self.login(self.client, "admin", "AdminPass123")
        self.assertEqual(
            self.client.post(
                f"/users/{self.admin_id}/role",
                data={"role": self.User.EMPLOYEE},
            ).status_code,
            400,
        )

        listing = self.client.get("/users/")
        response = self.client.post(
            f"/users/{self.admin_id}/role",
            data={
                "_csrf_token": self.csrf_token(listing),
                "role": self.User.EMPLOYEE,
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(self.User, self.admin_id).role,
                self.User.ADMIN,
            )

    def test_external_post_login_redirect_is_ignored(self):
        path = "/login?next=https://example.invalid/"
        response = self.login(self.client, "admin", "AdminPass123", path)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/")


if __name__ == "__main__":
    unittest.main()
