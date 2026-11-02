import os
import re
import unittest
from io import BytesIO
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
        from models.attendance import Attendance
        from models.department import Department
        from models import db
        from models.employee import Employee
        from models.leave import Leave
        from models.payroll import Payroll
        from models.payslip_request import PayslipRequest
        from models.record_audit import RecordAudit
        from models.travel_order import TravelOrder
        from models.user import User

        cls.db = db
        cls.Attendance = Attendance
        cls.Department = Department
        cls.Employee = Employee
        cls.Leave = Leave
        cls.Payroll = Payroll
        cls.PayslipRequest = PayslipRequest
        cls.RecordAudit = RecordAudit
        cls.TravelOrder = TravelOrder
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
            self.employee_id = self.employee.id
            self.hr_id = self.hr.id

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

    def test_admin_dashboard_combines_people_counts_and_shows_role_distribution(self):
        with self.app.app_context():
            department = self.Department(
                department_name="Operations",
                description="Business operations team",
            )
            self.db.session.add(department)
            self.db.session.flush()
            self.db.session.add(
                self.Employee(
                    user_id=self.employee_id,
                    first_name="Jamie",
                    last_name="Staff",
                    position="Analyst",
                    salary=60000,
                    department_id=department.id,
                )
            )
            self.db.session.get(self.User, self.hr_id).role = self.User.EMPLOYEE
            self.db.session.commit()

        self.login(self.client, "admin", "AdminPass123")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        self.assertEqual(content.count('class="hr-stat-card hr-stat-people"'), 1)
        self.assertIn("People &amp; Accounts", content)
        self.assertIn("Employee records", content)
        self.assertIn("User accounts", content)
        self.assertRegex(content, r'data-role="employee"\s+data-count="2"')
        self.assertRegex(content, r'data-role="hr"\s+data-count="0"')
        self.assertRegex(content, r'data-role="admin"\s+data-count="1"')
        self.assertIn("66.7%", content)
        self.assertIn("33.3%", content)
        self.assertIn("admin-overview-feature-grid", content)
        self.assertIn("admin-role-donut", content)
        self.assertIn('href="/users/role/employee/accounts"', content)
        self.assertIn('href="/users/role/hr/accounts"', content)
        self.assertIn('href="/users/role/admin/accounts"', content)
        self.assertEqual(content.count('class="hr-stat-card'), 5)

    def test_role_chart_account_lists_are_fresh_masked_and_admin_only(self):
        self.login(self.client, "admin", "AdminPass123")
        response = self.client.get("/users/role/admin/accounts")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Admin Accounts", response.data)
        self.assertIn(b"admin", response.data)
        self.assertIn(b"a****@example.test", response.data)
        self.assertNotIn(b"admin@example.test</span>", response.data)

        for username, password in (
            ("staff", "StaffPass123"),
            ("hrstaff", "HrPass123"),
        ):
            client = self.app.test_client()
            self.login(client, username, password)
            self.assertEqual(
                client.get("/users/role/admin/accounts").status_code,
                403,
            )

        with self.app.app_context():
            hr_user = self.db.session.get(self.User, self.hr_id)
            hr_user.role = self.User.ADMIN
            self.db.session.commit()
        updated_admins = self.client.get("/users/role/admin/accounts")
        self.assertEqual(updated_admins.status_code, 200)
        self.assertIn(b"2 accounts assigned the Admin role", updated_admins.data)
        no_hr_accounts = self.client.get("/users/role/hr/accounts")
        self.assertEqual(no_hr_accounts.status_code, 200)
        self.assertIn(b"No HR accounts yet", no_hr_accounts.data)

        self.assertEqual(
            self.client.get("/users/role/unknown/accounts").status_code,
            404,
        )

    def test_department_directory_cards_open_the_existing_detail_modal(self):
        with self.app.app_context():
            assigned = self.Department(
                department_name="Operations",
                description="Business operations team",
            )
            empty = self.Department(
                department_name="Research",
                description="Research and development",
            )
            self.db.session.add_all([assigned, empty])
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Jamie",
                last_name="Staff",
                position="Analyst",
                salary=60000,
                department_id=assigned.id,
            )
            self.db.session.add(employee)
            self.db.session.commit()
            assigned_id = assigned.id

        self.login(self.client, "admin", "AdminPass123")
        response = self.client.get("/departments/")
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        self.assertIn("department-directory-grid", content)
        self.assertIn("Business operations team", content)
        self.assertIn("Research and development", content)
        self.assertIn('data-record-modal', content)
        self.assertIn(f'href="/departments/{assigned_id}"', content)
        self.assertIn("1</strong>", content)

        employee_client = self.app.test_client()
        self.login(employee_client, "staff", "StaffPass123")
        employee_page = employee_client.get("/departments/")
        self.assertEqual(employee_page.status_code, 200)
        employee_content = employee_page.get_data(as_text=True)
        self.assertIn("OPERATIONS", employee_content)
        self.assertNotIn("Research", employee_content)
        self.assertNotIn("department-directory-summary", employee_content)
        self.assertNotIn(">Edit</a>", employee_content)

    def test_department_names_are_trimmed_uppercased_and_checked_without_case(self):
        self.login(self.client, "admin", "AdminPass123")
        form = self.client.get("/departments/add")
        response = self.client.post(
            "/departments/add",
            data={
                "_csrf_token": self.csrf_token(form),
                "department_name": "  hr department  ",
                "description": "A Description With Mixed Case",
            },
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            department = self.Department.query.one()
            self.assertEqual(department.department_name, "HR DEPARTMENT")
            self.assertEqual(department.description, "A Description With Mixed Case")
            department_id = department.id

        duplicate_form = self.client.get("/departments/add")
        duplicate_response = self.client.post(
            "/departments/add",
            data={
                "_csrf_token": self.csrf_token(duplicate_form),
                "department_name": "Hr Department",
                "description": "Do not replace the original",
            },
        )
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertIn(b"This department already exists.", duplicate_response.data)

        edit_form = self.client.get(f"/departments/{department_id}/edit")
        edit_response = self.client.post(
            f"/departments/{department_id}/edit",
            data={
                "_csrf_token": self.csrf_token(edit_form),
                "department_name": "  department of babae ro ",
                "description": "Description stays Mixed Case",
            },
        )
        self.assertEqual(edit_response.status_code, 302)
        with self.app.app_context():
            department = self.db.session.get(self.Department, department_id)
            self.assertEqual(department.department_name, "DEPARTMENT OF BABAE RO")
            self.assertEqual(department.description, "Description stays Mixed Case")
            model_created = self.Department(department_name="  people team  ")
            self.assertEqual(model_created.department_name, "PEOPLE TEAM")

    def test_legacy_department_names_render_uppercase_and_search_case_insensitively(self):
        from sqlalchemy import update

        with self.app.app_context():
            department = self.Department(
                department_name="Legacy department",
                description="Keep this description Mixed Case",
            )
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Jamie",
                last_name="Staff",
                position="Analyst",
                salary=60000,
                department_id=department.id,
            )
            self.db.session.add(employee)
            self.db.session.flush()
            self.db.session.execute(
                update(self.Department)
                .where(self.Department.id == department.id)
                .values(department_name="department of babae ro")
            )
            self.db.session.commit()
            department_id = department.id
            employee_id = employee.id

        self.login(self.client, "admin", "AdminPass123")
        for path in (
            "/departments/",
            f"/departments/{department_id}",
            "/employees/?q=Department%20Of%20Babae%20Ro",
            f"/employees/{employee_id}",
            "/employees/add",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                content = response.get_data(as_text=True)
                self.assertIn("DEPARTMENT OF BABAE RO", content)
                if path in ("/departments/", f"/departments/{department_id}"):
                    self.assertIn("Keep this description Mixed Case", content)

        employee_client = self.app.test_client()
        self.login(employee_client, "staff", "StaffPass123")
        for path in ("/employee/home", "/employees/", "/users/profile"):
            with self.subTest(path=path):
                response = employee_client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"DEPARTMENT OF BABAE RO", response.data)

    def test_attendance_pages_and_employee_dashboard_limit_records(self):
        from datetime import date, timedelta

        with self.app.app_context():
            department = self.Department(department_name="Performance")
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Jamie",
                last_name="Staff",
                position="Analyst",
                salary=60000,
                department_id=department.id,
            )
            self.db.session.add(employee)
            self.db.session.flush()
            self.db.session.add_all(
                [
                    self.Attendance(
                        employee_id=employee.id,
                        attendance_date=date(2026, 1, 1) + timedelta(days=day),
                        status="Present",
                    )
                    for day in range(51)
                ]
            )
            self.db.session.commit()

        self.login(self.client, "admin", "AdminPass123")
        page = self.client.get("/attendance/?page=2")
        self.assertEqual(page.status_code, 200)
        page_content = page.get_data(as_text=True)
        self.assertIn("Page 2 of 2 (51 records)", page_content)
        self.assertIn("2026-01-01", page_content)
        self.assertNotIn("2026-01-02", page_content)

        employee_client = self.app.test_client()
        self.login(employee_client, "staff", "StaffPass123")
        dashboard = employee_client.get("/employee/home")
        self.assertEqual(dashboard.status_code, 200)
        dashboard_content = dashboard.get_data(as_text=True)
        self.assertIn("2026-02-20", dashboard_content)
        self.assertNotIn("2026-01-01", dashboard_content)

    def test_record_detail_pages_render_structured_data_and_missing_values(self):
        from datetime import date
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Record details")
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Jamie",
                last_name="Staff",
                position="Analyst",
                salary=Decimal("50000.00"),
                department_id=department.id,
            )
            self.db.session.add(employee)
            self.db.session.flush()
            leave = self.Leave(
                employee_id=employee.id,
                leave_type="Personal",
                start_date=date(2026, 10, 20),
                end_date=date(2026, 10, 24),
                reason="Family care\nAdditional context",
            )
            attendance = self.Attendance(
                employee_id=employee.id,
                attendance_date=date(2026, 10, 20),
                status="Absent",
            )
            payroll = self.Payroll(
                employee_id=employee.id,
                pay_period_start=date(2026, 10, 1),
                pay_period_end=date(2026, 10, 31),
                basic_salary=Decimal("125000.00"),
                allowances=Decimal("1500.00"),
                deductions=Decimal("250.00"),
                net_pay=Decimal("126250.00"),
            )
            payslip_request = self.PayslipRequest(
                employee=employee,
                pay_period_start=date(2026, 8, 1),
                pay_period_end=date(2026, 8, 31),
                reason="Payslip not received",
            )
            self.db.session.add_all([leave, attendance, payroll, payslip_request])
            self.db.session.commit()
            leave_id = leave.id
            attendance_id = attendance.id
            payroll_id = payroll.id
            payslip_request_id = payslip_request.id

        self.login(self.client, "admin", "AdminPass123")
        leave_detail = self.client.get(f"/leaves/{leave_id}")
        self.assertEqual(leave_detail.status_code, 200)
        self.assertIn(b"Leave details", leave_detail.data)
        self.assertIn(b"October 20, 2026", leave_detail.data)
        self.assertIn(b"Family care", leave_detail.data)
        self.assertIn(b"EMP-0001", leave_detail.data)
        self.assertIn(b"Submitted", leave_detail.data)
        self.assertIn(b'data-leave-review', leave_detail.data)
        self.assertIn(b'data-review-decision="Approve"', leave_detail.data)
        self.assertIn(b'data-review-decision="Decline"', leave_detail.data)
        self.assertIn(b"employee-status-badge pending", leave_detail.data)

        attendance_detail = self.client.get(
            f"/attendance/{attendance_id}"
        )
        self.assertEqual(attendance_detail.status_code, 200)
        self.assertIn(b"Not recorded", attendance_detail.data)
        self.assertIn(b"employee-status-badge absent", attendance_detail.data)
        self.assertEqual(self.client.get("/attendance/d").status_code, 404)
        self.assertEqual(
            self.client.get("/attendance/999999").status_code,
            404,
        )

        payroll_detail = self.client.get(f"/payroll/{payroll_id}")
        self.assertEqual(payroll_detail.status_code, 200)
        self.assertIn(b"125,000.00", payroll_detail.data)
        self.assertIn(b"126,250.00", payroll_detail.data)
        self.assertIn(b"Pending payment", payroll_detail.data)

        hr_client = self.app.test_client()
        self.login(hr_client, "hrstaff", "HrPass123")
        review_detail = hr_client.get(
            f"/payslips/manage/{payslip_request_id}"
        )
        self.assertEqual(review_detail.status_code, 200)
        self.assertIn(b"Request details", review_detail.data)
        self.assertIn(b"No payroll record exists", review_detail.data)
        self.assertIn(b"employee-status-badge pending", review_detail.data)

    def test_employee_leave_submission_validates_and_persists_own_request(self):
        from datetime import date
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Leave submission")
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Jamie",
                last_name="Staff",
                position="Analyst",
                salary=Decimal("50000.00"),
                department_id=department.id,
            )
            other_employee = self.Employee(
                user_id=self.hr_id,
                first_name="Other",
                last_name="Staff",
                position="Coordinator",
                salary=Decimal("45000.00"),
                department_id=department.id,
            )
            self.db.session.add_all([employee, other_employee])
            self.db.session.commit()
            employee_id = employee.id
            other_employee_id = other_employee.id

        employee_client = self.app.test_client()
        self.login(employee_client, "staff", "StaffPass123")
        form = employee_client.get("/leaves/add")
        token = self.csrf_token(form)

        missing_fields = employee_client.post(
            "/leaves/add",
            data={"_csrf_token": token, "leave_type": "Annual"},
        )
        self.assertEqual(missing_fields.status_code, 200)
        self.assertIn(b"Please fill in all required fields.", missing_fields.data)

        invalid_dates = employee_client.post(
            "/leaves/add",
            data={
                "_csrf_token": token,
                "leave_type": "Annual",
                "start_date": "2026-02-31",
                "end_date": "2026-03-01",
            },
        )
        self.assertEqual(invalid_dates.status_code, 200)
        self.assertIn(b"Please enter valid dates.", invalid_dates.data)
        with self.app.app_context():
            self.assertEqual(self.Leave.query.count(), 0)

        response = employee_client.post(
            "/leaves/add",
            data={
                "_csrf_token": token,
                "employee_id": str(other_employee_id),
                "leave_type": "Annual",
                "start_date": "2026-11-10",
                "end_date": "2026-11-12",
                "reason": "Family commitment",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/leaves/")
        requests_page = employee_client.get(response.location)
        self.assertIn(b"Annual", requests_page.data)
        with self.app.app_context():
            leave = self.Leave.query.one()
            leave_id = leave.id
            self.assertEqual(leave.employee_id, employee_id)
            self.assertEqual(leave.start_date, date(2026, 11, 10))
            self.assertEqual(leave.status, "Pending")

        request_detail = employee_client.get(f"/leaves/{leave_id}")
        self.assertEqual(request_detail.status_code, 200)
        self.assertIn(b"Family commitment", request_detail.data)
        self.login(self.client, "admin", "AdminPass123")
        self.assertEqual(self.client.get("/leaves/add").status_code, 403)
        admin_form = self.client.get("/leaves/")
        self.assertEqual(
            self.client.post(
                "/leaves/add",
                data={
                    "_csrf_token": self.csrf_token(admin_form),
                    "employee_id": str(employee_id),
                    "leave_type": "Sick",
                    "start_date": "2026-11-15",
                    "end_date": "2026-11-16",
                },
            ).status_code,
            403,
        )
        with self.app.app_context():
            self.assertEqual(self.Leave.query.count(), 1)

    def test_hr_can_approve_and_decline_leave_requests_once(self):
        from datetime import date
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Leave review")
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Jamie",
                last_name="Staff",
                position="Analyst",
                salary=Decimal("50000.00"),
                department_id=department.id,
            )
            self.db.session.add(employee)
            self.db.session.flush()
            requests = [
                self.Leave(
                    employee_id=employee.id,
                    leave_type="Annual",
                    start_date=date(2026, 11, 10),
                    end_date=date(2026, 11, 12),
                    reason="Family event",
                ),
                self.Leave(
                    employee_id=employee.id,
                    leave_type="Sick",
                    start_date=date(2026, 11, 20),
                    end_date=date(2026, 11, 21),
                    reason="Medical appointment",
                ),
            ]
            self.db.session.add_all(requests)
            self.db.session.commit()
            approve_id, decline_id = (leave.id for leave in requests)

        self.login(self.client, "hrstaff", "HrPass123")
        for leave_id, status, expected_status in (
            (approve_id, "Approved", "Approved"),
            (decline_id, "Rejected", "Rejected"),
        ):
            detail = self.client.get(f"/leaves/{leave_id}")
            self.assertEqual(detail.status_code, 200)
            self.assertIn(b"Jamie Staff", detail.data)
            self.assertIn(b"EMP-0001", detail.data)
            self.assertIn(b"Submitted", detail.data)
            self.assertIn(b'data-leave-review', detail.data)
            response = self.client.post(
                f"/leaves/{leave_id}/status",
                data={
                    "_csrf_token": self.csrf_token(detail),
                    "status": status,
                },
            )
            self.assertEqual(response.status_code, 302)
            reviewed_detail = self.client.get(f"/leaves/{leave_id}")
            self.assertEqual(reviewed_detail.status_code, 200)
            self.assertIn(expected_status.encode(), reviewed_detail.data)
            self.assertNotIn(b'data-leave-review', reviewed_detail.data)
            self.assertIn(b"Review history", reviewed_detail.data)
            self.assertIn(b"hrstaff", reviewed_detail.data)
            self.assertEqual(
                self.client.post(
                    f"/leaves/{leave_id}/status",
                    data={
                        "_csrf_token": self.csrf_token(reviewed_detail),
                        "status": "Approved",
                    },
                ).status_code,
                409,
            )

        employee_client = self.app.test_client()
        self.login(employee_client, "staff", "StaffPass123")
        employee_detail = employee_client.get(f"/leaves/{approve_id}")
        self.assertEqual(
            employee_client.post(
                f"/leaves/{approve_id}/status",
                data={
                    "_csrf_token": self.csrf_token(employee_detail),
                    "status": "Approved",
                },
            ).status_code,
            403,
        )
        self.assertEqual(self.client.get("/leaves/999999").status_code, 404)

    def test_safe_error_handler_uses_html_for_pages_and_json_for_api(self):
        from app import create_app

        configured_app = create_app(
            {"SQLALCHEMY_DATABASE_URI": "sqlite://"}
        )
        self.assertFalse(configured_app.debug)
        with configured_app.app_context():
            self.db.engine.dispose()

        page_error = self.client.get("/attendance/d")
        self.assertEqual(page_error.status_code, 404)
        self.assertEqual(page_error.mimetype, "text/html")
        self.assertIn(b"Page not found", page_error.data)
        self.assertNotIn(b"Traceback", page_error.data)

        api_error = self.client.get(
            "/attendance/d",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(api_error.status_code, 404)
        self.assertEqual(api_error.mimetype, "application/json")
        self.assertIn(b'"error"', api_error.data)
        self.assertNotIn(b"Traceback", api_error.data)

    def test_database_failures_return_safe_503_responses(self):
        from sqlalchemy import event
        from sqlalchemy.exc import OperationalError

        self.login(self.client, "admin", "AdminPass123")

        def fail_database_query(
            connection,
            cursor,
            statement,
            parameters,
            context,
            executemany,
        ):
            raise OperationalError(
                "SELECT 1",
                {},
                RuntimeError("sensitive-test-database-detail"),
            )

        with self.app.app_context():
            engine = self.db.engine
            event.listen(
                engine,
                "before_cursor_execute",
                fail_database_query,
            )
            try:
                page_response = self.client.get(
                    "/attendance/",
                    headers={"Accept": "text/html"},
                )
                self.assertEqual(page_response.status_code, 503)
                self.assertEqual(page_response.mimetype, "text/html")
                self.assertIn(
                    b"The database is temporarily unavailable",
                    page_response.data,
                )
                self.assertNotIn(
                    b"sensitive-test-database-detail",
                    page_response.data,
                )
                self.assertNotIn(b"Traceback", page_response.data)

                api_response = self.client.get(
                    "/users/api",
                    headers={"Accept": "application/json"},
                )
                self.assertEqual(api_response.status_code, 503)
                self.assertEqual(api_response.mimetype, "application/json")
                self.assertNotIn(
                    b"sensitive-test-database-detail",
                    api_response.data,
                )
            finally:
                event.remove(
                    engine,
                    "before_cursor_execute",
                    fail_database_query,
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
                "role": self.User.ADMIN,
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(self.User, hr_user_id).role,
                self.User.ADMIN,
            )

    def test_admin_can_create_linked_employee_from_add_user_form(self):
        from decimal import Decimal

        self.login(self.client, "admin", "AdminPass123")
        with self.app.app_context():
            department = self.Department(department_name="New account team")
            self.db.session.add(department)
            self.db.session.commit()
            department_id = department.id

        form = self.client.get("/users/add")
        self.assertIn(b'value="employee"', form.data)
        self.assertIn(b"Employee", form.data)
        response = self.client.post(
            "/users/add",
            data={
                "_csrf_token": self.csrf_token(form),
                "username": "role-employee",
                "email": "role-employee@example.test",
                "password": "RoleEmployeePass123",
                "role": self.User.EMPLOYEE,
                "first_name": "Role",
                "last_name": "Employee",
                "position": "Analyst",
                "department_id": str(department_id),
                "salary": "52000.00",
            },
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            user = self.User.query.filter_by(username="role-employee").one()
            self.assertEqual(user.role, self.User.EMPLOYEE)
            self.assertIsNotNone(user.employee)
            self.assertEqual(user.employee.first_name, "Role")
            self.assertEqual(user.employee.department_id, department_id)
            self.assertEqual(user.employee.salary, Decimal("52000.00"))

    def test_admin_can_assign_employee_role_with_employee_position(self):
        from decimal import Decimal

        self.login(self.client, "admin", "AdminPass123")
        with self.app.app_context():
            department = self.Department(department_name="Role assignment")
            self.db.session.add(department)
            self.db.session.commit()
            department_id = department.id

        listing = self.client.get("/users/")
        self.assertIn(b'<option value="employee"', listing.data)
        response = self.client.post(
            f"/users/{self.hr_id}/role",
            data={
                "_csrf_token": self.csrf_token(listing),
                "role": self.User.EMPLOYEE,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            f"/users/{self.hr_id}/edit?role=employee",
            response.location,
        )

        form = self.client.get(response.location)
        self.assertEqual(form.status_code, 200)
        self.assertIn(b'id="position" name="position"', form.data)
        self.assertIn(b'<option value="employee"', form.data)
        response = self.client.post(
            f"/users/{self.hr_id}/edit",
            data={
                "_csrf_token": self.csrf_token(form),
                "username": "hrstaff",
                "email": "hrstaff@example.test",
                "role": self.User.EMPLOYEE,
                "first_name": "Casey",
                "last_name": "People",
                "position": "People Coordinator",
                "department_id": str(department_id),
                "salary": "53000.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = self.db.session.get(self.User, self.hr_id)
            self.assertEqual(user.role, self.User.EMPLOYEE)
            self.assertEqual(user.employee.position, "People Coordinator")
            self.assertEqual(user.employee.department_id, department_id)
            self.assertEqual(user.employee.salary, Decimal("53000.00"))

    def test_admin_dashboard_uses_management_dashboard_layout(self):
        self.login(self.client, "admin", "AdminPass123")
        dashboard = self.client.get("/")
        self.assertEqual(dashboard.status_code, 200)
        html = dashboard.get_data(as_text=True)
        self.assertIn("Organization overview", html)
        self.assertIn("hr-stat-grid", html)
        self.assertIn("hr-task-grid", html)
        self.assertIn("Users &amp; roles", html)
        self.assertIn("Review leave requests", html)
        self.assertNotIn("hr-task-primary", html)
        self.assertIn('id="skeleton-dashboard"', html)
        self.assertIn("Server-Timing", dashboard.headers)
        self.assertIn("database;dur=", dashboard.headers["Server-Timing"])
        self.assertIn("profile-storage;dur=", dashboard.headers["Server-Timing"])

    def test_date_filters_reject_reversed_ranges_and_date_sort_options_work(self):
        self.login(self.client, "admin", "AdminPass123")
        admin_routes = (
            ("/attendance/", "date"),
            ("/leaves/", "start_date"),
            ("/payroll/", "period"),
            ("/travel-orders/manage", "departure"),
        )
        for path, sort in admin_routes:
            with self.subTest(path=path, behavior="sort"):
                response = self.client.get(f"{path}?sort={sort}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    f'<option value="{sort}" selected>',
                    response.get_data(as_text=True),
                )
            with self.subTest(path=path, behavior="reversed range"):
                response = self.client.get(
                    f"{path}?from=2026-10-02&to=2026-10-01"
                )
                self.assertEqual(response.status_code, 400)

        employee_client = self.app.test_client()
        self.login(employee_client, "staff", "StaffPass123")
        response = employee_client.get("/travel-orders/?sort=departure")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            '<option value="departure" selected>',
            response.get_data(as_text=True),
        )
        response = employee_client.get(
            "/travel-orders/?from=2026-10-02&to=2026-10-01"
        )
        self.assertEqual(response.status_code, 400)

    def test_employee_information_uses_profile_layout_without_directory_controls(self):
        from datetime import datetime, timezone
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Employee information")
            self.db.session.add(department)
            self.db.session.flush()
            self.db.session.add(
                self.Employee(
                    user_id=self.employee_id,
                    first_name="Jamie",
                    last_name="Staff",
                    position="Analyst",
                    salary=Decimal("50000.00"),
                    department_id=department.id,
                    created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                )
            )
            self.db.session.commit()

        employee_client = self.app.test_client()
        self.login(employee_client, "staff", "StaffPass123")
        response = employee_client.get("/employees/?sort=department")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Jamie Staff", html)
        self.assertIn("Employee information", html)
        self.assertNotIn("View full profile", html)
        self.assertIn("Employment information", html)
        self.assertIn("Account information", html)
        self.assertIn("50,000.00", html)
        self.assertIn("EMPLOYEE ID", html)
        self.assertIn("October", html)
        self.assertNotIn('id="employee-sort"', html)
        self.assertNotIn('id="employee-direction"', html)
        self.assertNotIn('class="table-filters"', html)

        admin_client = self.app.test_client()
        self.login(admin_client, "admin", "AdminPass123")
        admin_directory = admin_client.get("/employees/")
        self.assertIn(b'id="employee-sort"', admin_directory.data)

    def test_date_range_forms_reuse_picker_and_single_date_fields_remain_single(self):
        from datetime import date
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Date range forms")
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Jamie",
                last_name="Staff",
                position="Analyst",
                salary=Decimal("50000.00"),
                department_id=department.id,
            )
            self.db.session.add(employee)
            self.db.session.flush()
            payroll = self.Payroll(
                employee_id=employee.id,
                pay_period_start=date(2026, 10, 1),
                pay_period_end=date(2026, 10, 15),
                basic_salary=Decimal("4000.00"),
                allowances=Decimal("0.00"),
                deductions=Decimal("0.00"),
                net_pay=Decimal("4000.00"),
            )
            self.db.session.add(payroll)
            self.db.session.commit()
            payroll_id = payroll.id

        employee_client = self.app.test_client()
        self.login(employee_client, "staff", "StaffPass123")
        for path, start_name, end_name in (
            ("/leaves/add", "start_date", "end_date"),
            ("/travel-orders/submit", "departure_date", "return_date"),
            ("/payslips/requests", "pay_period_start", "pay_period_end"),
        ):
            with self.subTest(path=path):
                response = employee_client.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertEqual(html.count('data-date-range'), 1)
                self.assertIn(f'name="{start_name}"', html)
                self.assertIn(f'name="{end_name}"', html)
                self.assertNotIn('type="date"', html)

        admin_client = self.app.test_client()
        self.login(admin_client, "admin", "AdminPass123")
        for path in ("/payroll/add", f"/payroll/{payroll_id}/edit"):
            with self.subTest(path=path):
                response = admin_client.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertEqual(html.count('data-date-range'), 1)
                self.assertIn('name="pay_period_start"', html)
                self.assertIn('name="pay_period_end"', html)
                self.assertIn('id="payment_date"', html)
                self.assertIn('type="date"', html)

    def test_payroll_list_avoids_separate_employee_queries(self):
        from datetime import date
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Payroll query")
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Jamie",
                last_name="Staff",
                position="Analyst",
                salary=Decimal("50000.00"),
                department_id=department.id,
            )
            self.db.session.add(employee)
            self.db.session.flush()
            self.db.session.add(
                self.Payroll(
                    employee_id=employee.id,
                    pay_period_start=date(2026, 10, 1),
                    pay_period_end=date(2026, 10, 15),
                    basic_salary=Decimal("4000.00"),
                    allowances=Decimal("100.00"),
                    deductions=Decimal("50.00"),
                    net_pay=Decimal("4050.00"),
                )
            )
            self.db.session.commit()

        self.login(self.client, "admin", "AdminPass123")
        response = self.client.get("/payroll/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Jamie Staff", response.get_data(as_text=True))
        self.assertIn(
            'desc="3 queries"',
            response.headers["Server-Timing"],
        )

    def test_deleting_linked_accounts_cleans_records_and_preserves_payroll(self):
        from datetime import date
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Deletion checks")
            self.db.session.add(department)
            self.db.session.flush()
            department_id = department.id

            payroll_employee = self.Employee(
                user_id=self.employee_id,
                first_name="Payroll",
                last_name="Protected",
                position="Analyst",
                salary=Decimal("50000.00"),
                department_id=department.id,
            )
            removable_employee = self.Employee(
                user_id=self.hr_id,
                first_name="Removable",
                last_name="Employee",
                position="Coordinator",
                salary=Decimal("45000.00"),
                department_id=department.id,
            )
            self.db.session.add_all([payroll_employee, removable_employee])
            self.db.session.flush()
            protected_employee_id = payroll_employee.id
            removable_employee_id = removable_employee.id
            removable_user_id = self.hr_id

            self.db.session.add_all(
                [
                    self.Attendance(
                        employee_id=payroll_employee.id,
                        attendance_date=date(2026, 10, 1),
                    ),
                    self.Leave(
                        employee_id=payroll_employee.id,
                        leave_type="Annual",
                        start_date=date(2026, 10, 5),
                        end_date=date(2026, 10, 6),
                    ),
                    self.Payroll(
                        employee_id=payroll_employee.id,
                        pay_period_start=date(2026, 9, 1),
                        pay_period_end=date(2026, 9, 30),
                        basic_salary=Decimal("4000.00"),
                        allowances=Decimal("0.00"),
                        deductions=Decimal("0.00"),
                        net_pay=Decimal("4000.00"),
                    ),
                    self.Attendance(
                        employee_id=removable_employee.id,
                        attendance_date=date(2026, 10, 2),
                    ),
                    self.Leave(
                        employee_id=removable_employee.id,
                        leave_type="Sick",
                        start_date=date(2026, 10, 7),
                        end_date=date(2026, 10, 8),
                    ),
                ]
            )
            self.db.session.commit()
            protected_payroll_id = self.Payroll.query.one().id

        self.login(self.client, "admin", "AdminPass123")
        response = self.client.get("/employees/")
        token = self.csrf_token(response)
        response = self.client.post(
            f"/employees/{protected_employee_id}/delete",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.post(
            f"/users/{self.employee_id}/delete",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNotNone(
                self.db.session.get(self.Employee, protected_employee_id)
            )
            self.assertIsNotNone(
                self.db.session.get(self.Payroll, protected_payroll_id)
            )

        response = self.client.post(
            f"/users/{removable_user_id}/delete",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNone(
                self.db.session.get(self.Employee, removable_employee_id)
            )
            self.assertIsNone(self.db.session.get(self.User, removable_user_id))
            self.assertEqual(self.Attendance.query.count(), 1)
            self.assertEqual(self.Leave.query.count(), 1)
            self.assertEqual(self.Payroll.query.count(), 1)

            employee_user = self.User(
                username="staff-two",
                email="staff-two@example.test",
                password_hash=generate_password_hash("StaffTwoPass123"),
                role=self.User.EMPLOYEE,
            )
            self.db.session.add(employee_user)
            self.db.session.flush()
            removable_employee = self.Employee(
                user=employee_user,
                first_name="Taylor",
                last_name="Staff",
                position="Assistant",
                salary=Decimal("42000.00"),
                department_id=department_id,
            )
            self.db.session.add(removable_employee)
            self.db.session.commit()
            employee_user_id = employee_user.id
            removable_employee_id = removable_employee.id

        response = self.client.post(
            f"/employees/{removable_employee_id}/delete",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNone(
                self.db.session.get(self.Employee, removable_employee_id)
            )
            self.assertIsNone(self.db.session.get(self.User, employee_user_id))

    def test_admin_can_edit_hr_account_and_employee_profile(self):
        from decimal import Decimal

        self.login(self.client, "admin", "AdminPass123")
        form = self.client.get("/users/add")
        response = self.client.post(
            "/users/add",
            data={
                "_csrf_token": self.csrf_token(form),
                "username": "hr-edit",
                "email": "hr-edit@example.test",
                "password": "HrEditPass123",
                "role": self.User.HR,
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            hr_user = self.User.query.filter_by(username="hr-edit").one()
            hr_user_id = hr_user.id

        form = self.client.get(f"/users/{hr_user_id}/edit")
        self.assertEqual(form.status_code, 200)
        self.assertIn(b"Account information", form.data)
        self.assertIn(b"Employee record", form.data)
        self.assertIn(b"No employee record is currently linked", form.data)
        self.assertIn(b"data-password-toggle", form.data)
        self.assertIn(b"Leave blank to keep the current password", form.data)
        response = self.client.post(
            f"/users/{hr_user_id}/edit",
            data={
                "_csrf_token": self.csrf_token(form),
                "username": "hr-updated",
                "email": "hr-updated@example.test",
                "role": self.User.HR,
                "new_password": "HrUpdatedPass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            updated_hr = self.db.session.get(self.User, hr_user_id)
            self.assertEqual(updated_hr.email, "hr-updated@example.test")
            self.assertEqual(updated_hr.role, self.User.HR)
            self.assertTrue(
                check_password_hash(
                    updated_hr.password_hash,
                    "HrUpdatedPass123",
                )
            )

        with self.app.app_context():
            department = self.Department(department_name="Salary edits")
            self.db.session.add(department)
            self.db.session.flush()
            employee_user = self.db.session.get(self.User, self.employee_id)
            employee = self.Employee(
                user=employee_user,
                first_name="Employee",
                last_name="Profile",
                position="Associate",
                salary=Decimal("40000.00"),
                department=department,
            )
            self.db.session.add(employee)
            self.db.session.commit()
            employee_id = employee.id
            department_id = department.id

        employee_account_form = self.client.get(
            f"/users/{self.employee_id}/edit"
        )
        self.assertEqual(employee_account_form.status_code, 200)
        self.assertIn(b"Linked to Employee Profile", employee_account_form.data)
        self.assertIn(
            f'href="/employees/{employee_id}/edit"'.encode(),
            employee_account_form.data,
        )
        employee_form = self.client.get(f"/employees/{employee_id}/edit")
        self.assertEqual(employee_form.status_code, 200)
        response = self.client.post(
            f"/employees/{employee_id}/edit",
            data={
                "_csrf_token": self.csrf_token(employee_form),
                "username": "staff",
                "email": "staff@example.test",
                "first_name": "Employee",
                "last_name": "Profile",
                "position": "Senior Associate",
                "department_id": str(department_id),
                "salary": "52000.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            updated_employee = self.db.session.get(
                self.Employee, employee_id
            )
            self.assertEqual(updated_employee.salary, Decimal("52000.00"))
            self.assertEqual(updated_employee.position, "Senior Associate")

        employee_client = self.app.test_client()
        self.login(employee_client, "staff", "StaffPass123")
        self.assertEqual(
            employee_client.get(f"/users/{hr_user_id}/edit").status_code,
            403,
        )
        self.assertEqual(
            employee_client.post(
                f"/users/{hr_user_id}/edit",
                data={"username": "hacked"},
            ).status_code,
            400,
        )

    def test_admin_can_complete_management_workflows(self):
        from datetime import date
        from decimal import Decimal

        self.login(self.client, "admin", "AdminPass123")
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"Quick actions", home.get_data())
        token = self.csrf_token(home)

        response = self.client.post(
            "/departments/add",
            data={
                "_csrf_token": token,
                "department_name": "Engineering",
                "description": "Product engineering",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            department = self.Department.query.filter_by(
                department_name="ENGINEERING"
            ).one()
            department_id = department.id

        response = self.client.post(
            "/employees/add",
            data={
                "_csrf_token": token,
                "username": "employee-one",
                "email": "employee-one@example.test",
                "password": "EmployeePass123",
                "first_name": "Jamie",
                "last_name": "One",
                "position": "Analyst",
                "department_id": str(department_id),
                "salary": "60000.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            employee = self.Employee.query.filter_by(
                first_name="Jamie"
            ).one()
            employee_id = employee.id
            employee_user_id = employee.user_id

        for path in (
            "/employees/",
            f"/employees/{employee_id}",
            f"/employees/{employee_id}/edit",
            "/departments/",
            f"/departments/{department_id}",
            f"/departments/{department_id}/edit",
            "/attendance/",
            "/attendance/add",
            "/leaves/",
            "/payroll/",
            "/payroll/add",
            "/users/",
            "/users/add",
            "/users/profile",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get("/leaves/add").status_code, 403)

        response = self.client.post(
            "/attendance/add",
            data={
                "_csrf_token": token,
                "employee_id": str(employee_id),
                "attendance_date": "2026-10-01",
                "time_in": "09:00",
                "time_out": "17:00",
                "status": "Present",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            attendance = self.Attendance.query.one()
            attendance_id = attendance.id

        response = self.client.post(
            f"/attendance/{attendance_id}/edit",
            data={
                "_csrf_token": token,
                "employee_id": str(employee_id),
                "attendance_date": "2026-10-02",
                "time_in": "09:15",
                "time_out": "17:00",
                "status": "Late",
                "reason": "Corrected the recorded late arrival time.",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            attendance = self.db.session.get(self.Attendance, attendance_id)
            self.assertEqual(attendance.status, "Late")

        employee_client = self.app.test_client()
        self.login(employee_client, "employee-one", "EmployeePass123")
        leave_form = employee_client.get("/leaves/add")
        response = employee_client.post(
            "/leaves/add",
            data={
                "_csrf_token": self.csrf_token(leave_form),
                "employee_id": str(self.employee_id),
                "leave_type": "Annual",
                "start_date": "2026-10-05",
                "end_date": "2026-10-06",
                "reason": "Personal plans",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            leave = self.Leave.query.one()
            leave_id = leave.id
            self.assertEqual(leave.employee_id, employee_id)

        response = self.client.post(
            f"/leaves/{leave_id}/status",
            data={"_csrf_token": token, "status": "Approved"},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(self.Leave, leave_id).status,
                "Approved",
            )
            leave_audit = self.RecordAudit.query.filter_by(
                record_type="leave",
                record_id=leave_id,
            ).one()
            self.assertEqual(leave_audit.actor_username, "admin")
            self.assertEqual(leave_audit.after_values["status"], "Approved")
        self.assertEqual(
            self.client.post(
                f"/leaves/{leave_id}/status",
                data={"_csrf_token": token, "status": "Rejected"},
            ).status_code,
            409,
        )

        response = self.client.post(
            "/payroll/add",
            data={
                "_csrf_token": token,
                "employee_id": str(employee_id),
                "pay_period_start": "2026-10-01",
                "pay_period_end": "2026-10-15",
                "basic_salary": "3000.00",
                "allowances": "100.00",
                "deductions": "50.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            payroll = self.Payroll.query.one()
            payroll_id = payroll.id
            self.assertEqual(payroll.net_pay, Decimal("3050.00"))

        response = self.client.post(
            f"/payroll/{payroll_id}/edit",
            data={
                "_csrf_token": token,
                "employee_id": str(employee_id),
                "pay_period_start": "2026-10-01",
                "pay_period_end": "2026-10-15",
                "basic_salary": "3200.00",
                "allowances": "100.00",
                "deductions": "50.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            payroll = self.db.session.get(self.Payroll, payroll_id)
            self.assertEqual(payroll.net_pay, Decimal("3250.00"))

        response = self.client.post(
            f"/payroll/{payroll_id}/edit",
            data={
                "_csrf_token": token,
                "employee_id": str(employee_id),
                "pay_period_start": "2026-10-01",
                "pay_period_end": "2026-10-15",
                "basic_salary": "3200.00",
                "allowances": "100.00",
                "deductions": "5000.00",
            },
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            payroll = self.db.session.get(self.Payroll, payroll_id)
            self.assertEqual(payroll.net_pay, Decimal("3250.00"))

        response = self.client.post(
            f"/payroll/{payroll_id}/edit",
            data={
                "_csrf_token": token,
                "employee_id": str(employee_id),
                "pay_period_start": "2026-10-01",
                "pay_period_end": "2026-10-15",
                "payment_date": "2026-10-17",
                "basic_salary": "3200.00",
                "allowances": "100.00",
                "deductions": "50.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            payroll = self.db.session.get(self.Payroll, payroll_id)
            self.assertEqual(payroll.payment_date, date(2026, 10, 17))

        response = self.client.post(
            f"/employees/{employee_id}/edit",
            data={
                "_csrf_token": token,
                "username": "employee-one",
                "email": "employee-one@example.test",
                "first_name": "Jamie",
                "last_name": "Updated",
                "position": "Senior Analyst",
                "department_id": str(department_id),
                "salary": "62000.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(self.Employee, employee_id).last_name,
                "Updated",
            )
            self.assertEqual(
                self.db.session.get(self.Employee, employee_id).salary,
                Decimal("62000.00"),
            )

        for path in (
            f"/attendance/{attendance_id}/delete",
            f"/leaves/{leave_id}/delete",
        ):
            data = {"_csrf_token": token}
            if path.startswith("/attendance/"):
                data["reason"] = "Duplicate attendance record."
            response = self.client.post(path, data=data)
            with self.subTest(path=path):
                self.assertEqual(response.status_code, 302)

        self.client.get("/users/")
        user_response = self.client.post(
            f"/users/{employee_user_id}/role",
            data={"_csrf_token": token, "role": self.User.HR},
        )
        self.assertEqual(user_response.status_code, 302)

    def test_hr_can_manage_employees_but_not_accounts(self):
        self.login(self.client, "hrstaff", "HrPass123")
        for path in (
            "/attendance/add",
            "/departments/add",
            "/payroll/add",
            "/employees/",
            "/employees/add",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get("/leaves/add").status_code, 403)
        for path in (
            "/users/",
            "/users/add",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_hr_can_add_edit_assign_employees_manage_departments_and_approve_leave(self):
        from datetime import date
        from decimal import Decimal

        self.login(self.client, "hrstaff", "HrPass123")
        form = self.client.get("/departments/add")
        response = self.client.post(
            "/departments/add",
            data={
                "_csrf_token": self.csrf_token(form),
                "department_name": "People Operations",
                "description": "Human resources",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            department = self.Department.query.filter_by(
                department_name="PEOPLE OPERATIONS"
            ).one()
            department_id = department.id

        form = self.client.get("/employees/add")
        response = self.client.post(
            "/employees/add",
            data={
                "_csrf_token": self.csrf_token(form),
                "username": "new-staff",
                "email": "new-staff@example.test",
                "password": "NewStaffPass123",
                "role": self.User.ADMIN,
                "first_name": "New",
                "last_name": "Staff",
                "position": "Coordinator",
                "department_id": str(department_id),
                "salary": "45000.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            new_user = self.User.query.filter_by(username="new-staff").one()
            self.assertEqual(new_user.role, self.User.EMPLOYEE)
            employee = new_user.employee
            employee_id = employee.id

        form = self.client.get(f"/departments/{department_id}/edit")
        response = self.client.post(
            f"/departments/{department_id}/edit",
            data={
                "_csrf_token": self.csrf_token(form),
                "department_name": "People",
                "description": "People team",
            },
        )
        self.assertEqual(response.status_code, 302)
        form = self.client.get("/departments/add")
        response = self.client.post(
            "/departments/add",
            data={
                "_csrf_token": self.csrf_token(form),
                "department_name": "Finance",
                "description": "Finance team",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            finance_department_id = self.Department.query.filter_by(
                department_name="FINANCE"
            ).one().id

        form = self.client.get(f"/employees/{employee_id}/edit")
        self.assertEqual(form.status_code, 200)
        self.assertNotIn(b'name="username"', form.get_data())
        response = self.client.post(
            f"/employees/{employee_id}/edit",
            data={
                "_csrf_token": self.csrf_token(form),
                "username": "attempted-account-edit",
                "email": "attempted@example.test",
                "first_name": "Updated",
                "last_name": "Staff",
                "position": "Senior Coordinator",
                "department_id": str(finance_department_id),
                "salary": "47000.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            updated_employee = self.db.session.get(
                self.Employee, employee_id
            )
            self.assertEqual(updated_employee.first_name, "Updated")
            self.assertEqual(updated_employee.position, "Senior Coordinator")
            self.assertEqual(updated_employee.department_id, finance_department_id)
            self.assertEqual(updated_employee.salary, Decimal("47000.00"))
            self.assertEqual(updated_employee.user.username, "new-staff")
            self.assertEqual(
                updated_employee.user.email,
                "new-staff@example.test",
            )
            leave = self.Leave(
                employee_id=employee_id,
                leave_type="Annual",
                start_date=date(2026, 10, 20),
                end_date=date(2026, 10, 21),
            )
            self.db.session.add(leave)
            self.db.session.commit()
            leave_id = leave.id

        form = self.client.get(f"/leaves/{leave_id}")
        leave_detail = form.get_data(as_text=True)
        self.assertIn('name="status" value="Approved"', leave_detail)
        self.assertIn('name="status" value="Rejected"', leave_detail)
        self.assertNotIn('<select id="status"', leave_detail)
        response = self.client.post(
            f"/leaves/{leave_id}/status",
            data={
                "_csrf_token": self.csrf_token(form),
                "status": "Approved",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(self.Leave, leave_id).status,
                "Approved",
            )
            denied_leave = self.Leave(
                employee_id=employee_id,
                leave_type="Sick",
                start_date=date(2026, 10, 22),
                end_date=date(2026, 10, 23),
            )
            self.db.session.add(denied_leave)
            self.db.session.commit()
            denied_leave_id = denied_leave.id

        form = self.client.get(f"/leaves/{denied_leave_id}")
        response = self.client.post(
            f"/leaves/{denied_leave_id}/status",
            data={
                "_csrf_token": self.csrf_token(form),
                "status": "Rejected",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(self.Leave, denied_leave_id).status,
                "Rejected",
            )

        with self.app.app_context():
            department = self.db.session.get(
                self.Department, finance_department_id
            )
            management_employees = [
                self.Employee(
                    user_id=user_id,
                    first_name=first_name,
                    last_name="Account",
                    position="Manager",
                    salary=Decimal("80000.00"),
                    department=department,
                )
                for user_id, first_name in (
                    (self.admin_id, "Admin"),
                    (self.hr_id, "HR"),
                )
            ]
            self.db.session.add_all(management_employees)
            self.db.session.commit()
            admin_employee_id, hr_employee_id = (
                employee.id for employee in management_employees
            )

        employee_list = self.client.get("/employees/")
        employee_list_html = employee_list.get_data(as_text=True)
        self.assertIn(b"Add employee", employee_list.get_data())
        self.assertIn(b"new-staff", employee_list.get_data())
        self.assertIn(b"hrstaff@example.test", employee_list.get_data())
        self.assertIn(b"admin@example.test", employee_list.get_data())
        self.assertIn(b">Hr<", employee_list.get_data())
        self.assertIn(b">Admin<", employee_list.get_data())
        self.assertNotIn(
            f'href="/employees/{hr_employee_id}/edit"',
            employee_list_html,
        )
        self.assertNotIn(
            f'href="/employees/{admin_employee_id}/edit"',
            employee_list_html,
        )
        self.assertIn(
            f'href="/employees/{employee_id}/edit"',
            employee_list_html,
        )
        self.assertEqual(
            self.client.get(f"/employees/link-user/{self.hr_id}").status_code,
            403,
        )
        self.assertEqual(
            self.client.get(f"/employees/{hr_employee_id}").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/employees/{hr_employee_id}/edit").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/employees/{admin_employee_id}/edit").status_code,
            404,
        )

    def test_hr_dashboard_shows_current_attendance_and_payroll_counts(self):
        from datetime import date
        from decimal import Decimal

        today = date.today()
        with self.app.app_context():
            department = self.Department(department_name="HR overview")
            self.db.session.add(department)
            self.db.session.flush()
            employees = [
                self.Employee(
                    user_id=user_id,
                    first_name=first_name,
                    last_name="Overview",
                    position="Associate",
                    salary=Decimal("40000.00"),
                    department_id=department.id,
                )
                for user_id, first_name in (
                    (self.employee_id, "Present"),
                    (self.hr_id, "Absent"),
                )
            ]
            self.db.session.add_all(employees)
            self.db.session.flush()
            self.db.session.add_all(
                [
                    self.Attendance(
                        employee_id=employees[0].id,
                        attendance_date=today,
                        status="Present",
                    ),
                    self.Attendance(
                        employee_id=employees[1].id,
                        attendance_date=today,
                        status="Absent",
                    ),
                    self.Leave(
                        employee_id=employees[0].id,
                        leave_type="Annual",
                        start_date=today,
                        end_date=today,
                        status="Pending",
                    ),
                    self.Payroll(
                        employee_id=employees[0].id,
                        pay_period_start=today,
                        pay_period_end=today,
                        basic_salary=Decimal("4000.00"),
                        allowances=Decimal("0.00"),
                        deductions=Decimal("0.00"),
                        net_pay=Decimal("4000.00"),
                    ),
                    self.Payroll(
                        employee_id=employees[1].id,
                        pay_period_start=today,
                        pay_period_end=today,
                        basic_salary=Decimal("4000.00"),
                        allowances=Decimal("0.00"),
                        deductions=Decimal("0.00"),
                        net_pay=Decimal("4000.00"),
                        payment_date=today,
                    ),
                ]
            )
            self.db.session.commit()

        hr_client = self.app.test_client()
        self.login(hr_client, "hrstaff", "HrPass123")
        response = hr_client.get("/hr/home")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for metric, count in (
            ("employees", 2),
            ("present", 1),
            ("absent", 1),
            ("leave", 1),
            ("departments", 1),
            ("payroll", 2),
        ):
            with self.subTest(metric=metric):
                self.assertRegex(
                    html,
                    rf'data-stat="{metric}">{count}</strong>',
                )
        self.assertIn("1 payroll record awaiting payment", html)
        self.assertNotIn("/employees/add", html)

    def test_hr_can_create_and_edit_payroll_records_but_not_delete(self):
        from datetime import date
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Payroll HR")
            self.db.session.add(department)
            self.db.session.flush()
            employee_user = self.db.session.get(self.User, self.employee_id)
            employee = self.Employee(
                user=employee_user,
                first_name="Payroll",
                last_name="Employee",
                position="Specialist",
                salary=Decimal("50000.00"),
                department=department,
            )
            self.db.session.add(employee)
            self.db.session.commit()
            employee_id = employee.id

        self.login(self.client, "hrstaff", "HrPass123")
        form = self.client.get("/payroll/add")
        token = self.csrf_token(form)
        response = self.client.post(
            "/payroll/add",
            data={
                "_csrf_token": token,
                "employee_id": str(employee_id),
                "pay_period_start": "2026-10-01",
                "pay_period_end": "2026-10-31",
                "basic_salary": "4000.00",
                "allowances": "200.00",
                "deductions": "100.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            payroll = self.Payroll.query.one()
            payroll_id = payroll.id
            self.assertEqual(payroll.net_pay, Decimal("4100.00"))

        response = self.client.post(
            f"/payroll/{payroll_id}/edit",
            data={
                "_csrf_token": token,
                "employee_id": str(employee_id),
                "pay_period_start": "2026-10-01",
                "pay_period_end": "2026-10-31",
                "payment_date": "2026-11-05",
                "basic_salary": "4200.00",
                "allowances": "200.00",
                "deductions": "100.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            payroll = self.db.session.get(self.Payroll, payroll_id)
            self.assertEqual(payroll.net_pay, Decimal("4300.00"))
            self.assertEqual(payroll.payment_date, date(2026, 11, 5))

        response = self.client.post(
            f"/payroll/{payroll_id}/delete",
            data={"_csrf_token": token},
        )
        self.assertEqual(response.status_code, 404)
        with self.app.app_context():
            self.assertIsNotNone(self.db.session.get(self.Payroll, payroll_id))

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
            b"Your employee portal",
            home.get_data(),
        )
        self.assertEqual(self.client.get("/").location, "/employee/home")
        self.assertEqual(self.client.get("/users/").status_code, 403)
        self.assertEqual(self.client.get("/employees/add").status_code, 403)

    def test_employee_navigation_works_without_a_linked_employee_record(self):
        self.login(self.client, "staff", "StaffPass123")
        for path in (
            "/employee/home",
            "/employees/",
            "/departments/",
            "/attendance/",
            "/leaves/",
            "/leaves/add",
            "/payslips/",
            "/payslips/requests",
            "/users/profile",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
        self.assertIn(
            b"not linked to an employee record",
            self.client.get("/leaves/add").get_data().lower(),
        )

    def test_admin_employee_navigation_lists_all_employee_records(self):
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Support")
            self.db.session.add(department)
            self.db.session.flush()
            for first_name, username in (
                ("Avery", "avery"),
                ("Morgan", "morgan"),
            ):
                user = self.User(
                    username=username,
                    email=f"{username}@example.test",
                    password_hash=generate_password_hash("EmployeePass123"),
                    role=self.User.EMPLOYEE,
                )
                self.db.session.add(
                    self.Employee(
                        user=user,
                        first_name=first_name,
                        last_name="Staff",
                        position="Representative",
                        salary=Decimal("40000.00"),
                        department=department,
                    )
                )
            self.db.session.commit()

        self.login(self.client, "admin", "AdminPass123")
        response = self.client.get("/employees/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Avery Staff", response.get_data())
        self.assertIn(b"Morgan Staff", response.get_data())
        self.assertIn(b"admin@example.test", response.get_data())
        self.assertIn(b"hrstaff@example.test", response.get_data())
        self.assertIn(b"Users and Employees", response.get_data())
        self.assertIn(b'class="sidebar-account-profile', response.get_data())
        self.assertEqual(response.get_data().count(b"Sign out"), 1)
        self.assertNotIn(b"Edit Profile", response.get_data())
        self.assertEqual(self.client.get("/users/profile").status_code, 200)

    def test_admin_can_assign_existing_user_to_department(self):
        self.login(self.client, "admin", "AdminPass123")
        token = self.csrf_token(self.client.get("/"))
        response = self.client.post(
            "/departments/add",
            data={
                "_csrf_token": token,
                "department_name": "Operations",
                "description": "Operations department",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            department_id = self.Department.query.filter_by(
                department_name="OPERATIONS"
            ).one().id

        response = self.client.post(
            "/users/add",
            data={
                "_csrf_token": token,
                "username": "unassigned",
                "email": "unassigned@example.test",
                "password": "UnassignedPass123",
                "role": self.User.HR,
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user_id = self.User.query.filter_by(username="unassigned").one().id

        listing = self.client.get("/employees/")
        self.assertIn(b"Assign department", listing.get_data())
        form = self.client.get(f"/employees/link-user/{user_id}")
        self.assertEqual(form.status_code, 200)
        self.assertIn(b"OPERATIONS", form.get_data())
        response = self.client.post(
            f"/employees/link-user/{user_id}",
            data={
                "_csrf_token": self.csrf_token(form),
                "first_name": "Robin",
                "last_name": "Unassigned",
                "position": "Coordinator",
                "department_id": str(department_id),
                "salary": "45000.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = self.db.session.get(self.User, user_id)
            self.assertEqual(user.role, self.User.HR)
            self.assertEqual(user.employee.department_id, department_id)

    def test_admin_and_hr_account_totals_include_all_roles(self):
        self.login(self.client, "admin", "AdminPass123")

        def account_total(response):
            match = re.search(
                rb"<strong>(\d+)</strong>\s*"
                rb"(?:<small>User accounts</small>|"
                rb"<span>Accounts \(all roles\)</span>)",
                response.data,
            )
            self.assertIsNotNone(match)
            return int(match.group(1))

        self.assertEqual(account_total(self.client.get("/")), 3)
        form = self.client.get("/users/add")
        response = self.client.post(
            "/users/add",
            data={
                "_csrf_token": self.csrf_token(form),
                "username": "second-admin",
                "email": "second-admin@example.test",
                "password": "SecondAdminPass123",
                "role": self.User.ADMIN,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(account_total(self.client.get("/")), 4)

        with self.app.app_context():
            department = self.Department(department_name="Dashboard")
            self.db.session.add(department)
            self.db.session.commit()
            department_id = department.id
        form = self.client.get("/employees/add")
        response = self.client.post(
            "/employees/add",
            data={
                "_csrf_token": self.csrf_token(form),
                "username": "dashboard-employee",
                "email": "dashboard-employee@example.test",
                "password": "DashboardPass123",
                "first_name": "Dashboard",
                "last_name": "Employee",
                "position": "Assistant",
                "department_id": str(department_id),
                "salary": "40000.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(account_total(self.client.get("/")), 5)

        hr_client = self.app.test_client()
        self.login(hr_client, "hrstaff", "HrPass123")
        self.assertEqual(account_total(hr_client.get("/hr/home")), 5)

    def test_role_sidebar_highlights_only_the_current_section(self):
        cases = (
            (
                "admin",
                "AdminPass123",
                "/users/profile",
                'href="/users/"',
                'href="/users/profile"',
            ),
            (
                "hrstaff",
                "HrPass123",
                "/users/profile",
                'href="/employees/"',
                'href="/users/profile"',
            ),
            (
                "staff",
                "StaffPass123",
                "/leaves/add",
                'href="/leaves/"',
                'href="/leaves/add"',
            ),
        )
        for username, password, path, inactive_href, active_href in cases:
            with self.subTest(path=path):
                client = self.app.test_client()
                self.login(client, username, password)
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                inactive_start = html.index(inactive_href)
                inactive_end = html.index("</a>", inactive_start)
                self.assertNotIn(
                    "active",
                    html[inactive_start:inactive_end],
                )
                active_start = html.index(active_href)
                active_end = html.index("</a>", active_start)
                self.assertIn(
                    "active",
                    html[active_start:active_end],
                )

    def test_employee_routes_are_scoped_to_their_own_records(self):
        from datetime import date
        from decimal import Decimal

        with self.app.app_context():
            own_department = self.Department(
                department_name="Engineering",
                description="Own department",
            )
            other_department = self.Department(
                department_name="Finance",
                description="Other department",
            )
            self.db.session.add_all([own_department, other_department])
            self.db.session.flush()
            own_user = self.db.session.get(self.User, self.employee_id)
            other_user = self.db.session.get(self.User, self.hr_id)
            own_employee = self.Employee(
                user=own_user,
                first_name="Staff",
                last_name="Member",
                position="Developer",
                salary=Decimal("70000.00"),
                department=own_department,
            )
            other_employee = self.Employee(
                user=other_user,
                first_name="HR",
                last_name="Member",
                position="Manager",
                salary=Decimal("90000.00"),
                department=other_department,
            )
            self.db.session.add_all([own_employee, other_employee])
            self.db.session.flush()
            own_attendance = self.Attendance(
                employee=own_employee,
                attendance_date=date(2026, 10, 1),
                status="Present",
            )
            other_attendance = self.Attendance(
                employee=other_employee,
                attendance_date=date(2026, 10, 1),
                status="Absent",
            )
            own_leave = self.Leave(
                employee=own_employee,
                leave_type="Vacation",
                start_date=date(2026, 10, 5),
                end_date=date(2026, 10, 6),
                status="Pending",
            )
            other_leave = self.Leave(
                employee=other_employee,
                leave_type="Sick",
                start_date=date(2026, 10, 5),
                end_date=date(2026, 10, 6),
                status="Pending",
            )
            own_payroll = self.Payroll(
                employee=own_employee,
                pay_period_start=date(2026, 9, 1),
                pay_period_end=date(2026, 9, 30),
                basic_salary=Decimal("5000.00"),
                allowances=Decimal("0.00"),
                deductions=Decimal("0.00"),
                net_pay=Decimal("5000.00"),
                payment_date=date(2026, 10, 1),
            )
            other_payroll = self.Payroll(
                employee=other_employee,
                pay_period_start=date(2026, 9, 1),
                pay_period_end=date(2026, 9, 30),
                basic_salary=Decimal("7000.00"),
                allowances=Decimal("0.00"),
                deductions=Decimal("0.00"),
                net_pay=Decimal("7000.00"),
                payment_date=date(2026, 10, 1),
            )
            self.db.session.add_all(
                [
                    own_attendance,
                    other_attendance,
                    own_leave,
                    other_leave,
                    own_payroll,
                    other_payroll,
                ]
            )
            self.db.session.commit()
            own_employee_id = own_employee.id
            other_employee_id = other_employee.id
            own_department_id = own_department.id
            other_department_id = other_department.id
            own_attendance_id = own_attendance.id
            other_attendance_id = other_attendance.id
            own_leave_id = own_leave.id
            other_leave_id = other_leave.id
            own_payroll_id = own_payroll.id
            other_payroll_id = other_payroll.id

        self.login(self.client, "staff", "StaffPass123")
        home = self.client.get("/employee/home")
        self.assertIn(b"ENGINEERING", home.get_data())
        self.assertIn(b"5000.00", home.get_data())
        self.assertIn(b"My Department", home.get_data())
        self.assertIn(b"My Attendance", home.get_data())
        self.assertIn(b"My Payslips", home.get_data())
        self.assertNotIn(b"My Payroll", home.get_data())
        self.assertIn(b'class="sidebar-account-profile', home.get_data())
        self.assertEqual(home.get_data().count(b"Sign out"), 1)
        self.assertNotIn(b"Edit Profile", home.get_data())
        self.assertNotIn(b"Users &amp; Roles", home.get_data())
        self.assertNotIn(b">Employees<", home.get_data())
        self.assertNotIn(b"Finance", home.get_data())
        self.assertNotIn(b"7000.00", home.get_data())
        own_routes = (
            f"/employees/{own_employee_id}",
            f"/departments/{own_department_id}",
            f"/attendance/{own_attendance_id}",
            f"/leaves/{own_leave_id}",
            f"/payslips/{own_payroll_id}",
        )
        other_routes = (
            f"/employees/{other_employee_id}",
            f"/departments/{other_department_id}",
            f"/attendance/{other_attendance_id}",
            f"/leaves/{other_leave_id}",
            f"/payslips/{other_payroll_id}",
        )
        for path in own_routes:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        for path in other_routes:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        for path in ("/payroll/", f"/payroll/{own_payroll_id}"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)

        csrf_page = self.client.get("/employee/home")
        token = self.csrf_token(csrf_page)
        for path in (
            "/attendance/add",
            "/payroll/add",
            "/departments/add",
            f"/payroll/{own_payroll_id}/edit",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.get(f"/payroll/{own_payroll_id}").status_code, 403)
        self.assertEqual(self.client.get("/payroll/").status_code, 403)
        self.assertEqual(
            self.client.post(
                f"/payroll/{own_payroll_id}/delete",
                data={"_csrf_token": token},
            ).status_code,
            404,
        )

        self.assertEqual(
            self.client.post(
                f"/leaves/{own_leave_id}/status",
                data={"_csrf_token": token, "status": "Approved"},
            ).status_code,
            403,
        )

        response = self.client.post(
            "/leaves/add",
            data={
                "_csrf_token": token,
                "employee_id": str(other_employee_id),
                "leave_type": "Personal",
                "start_date": "2026-10-10",
                "end_date": "2026-10-11",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            submitted_leave = self.Leave.query.filter_by(
                leave_type="Personal"
            ).one()
            self.assertEqual(submitted_leave.employee_id, own_employee_id)

    def test_users_can_edit_their_own_profile_and_password(self):
        response = self.login(self.client, "staff", "StaffPass123")
        self.assertEqual(response.status_code, 302)
        profile = self.client.get("/users/profile")
        self.assertEqual(profile.status_code, 200)
        self.assertIn(b'name="email"', profile.get_data())
        self.assertIn(b"person-avatar-fallback", profile.get_data())
        response = self.client.post(
            "/users/profile",
            data={
                "_csrf_token": self.csrf_token(profile),
                "username": "admin",
                "email": "duplicate@example.test",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'value="admin"', response.get_data())
        self.assertIn(b'value="duplicate@example.test"', response.get_data())
        self.assertIn(b'<div id="accountSettings">', response.get_data())

        response = self.client.post(
            "/users/profile",
            data={
                "_csrf_token": self.csrf_token(response),
                "username": "staff-updated",
                "email": "staff-updated@example.test",
                "current_password": "StaffPass123",
                "new_password": "NewStaffPass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = self.db.session.get(self.User, self.employee_id)
            self.assertEqual(user.username, "staff-updated")
            self.assertEqual(user.email, "staff-updated@example.test")
            self.assertTrue(
                check_password_hash(user.password_hash, "NewStaffPass123")
            )
        self.assertEqual(
            self.login(
                self.app.test_client(),
                "staff-updated",
                "NewStaffPass123",
            ).status_code,
            302,
        )

    def test_employee_can_upload_own_profile_picture(self):
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Profile Photos")
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Jamie",
                last_name="Staff",
                position="Analyst",
                salary=Decimal("50000.00"),
                department_id=department.id,
            )
            self.db.session.add(employee)
            self.db.session.commit()
            employee_id = employee.id

        self.login(self.client, "staff", "StaffPass123")
        profile = self.client.get("/users/profile")
        self.assertIn(b'action="/users/profile/picture"', profile.get_data())

        with patch(
            "routes.user_routes.save_profile_picture",
            return_value=("employee_1_new.jpg", None),
        ):
            response = self.client.post(
                "/users/profile/picture",
                data={
                    "_csrf_token": self.csrf_token(profile),
                    "profile_picture": (BytesIO(b"test image"), "avatar.jpg"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/users/profile")
        with self.app.app_context():
            employee = self.db.session.get(self.Employee, employee_id)
            self.assertEqual(employee.profile_picture, "employee_1_new.jpg")

    def test_employee_directory_shows_profile_picture_by_employee_name(self):
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Directory Photos")
            self.db.session.add(department)
            self.db.session.flush()
            self.db.session.add(
                self.Employee(
                    user_id=self.employee_id,
                    first_name="Jamie",
                    last_name="Staff",
                    position="Analyst",
                    salary=Decimal("50000.00"),
                    department_id=department.id,
                    profile_picture="employee_1_photo.jpg",
                )
            )
            self.db.session.commit()

        self.login(self.client, "admin", "AdminPass123")
        with patch(
            "routes.employee_routes.profile_picture_urls",
            return_value={
                "employee_1_photo.jpg": "https://example.test/signed-photo"
            },
        ):
            response = self.client.get("/employees/")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('src="https://example.test/signed-photo"', html)
        self.assertIn("Jamie Staff", html)

    def test_admin_login_stays_on_shared_dashboard(self):
        response = self.login(self.client, "admin", "AdminPass123")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/")

    def test_hr_login_uses_hr_dashboard(self):
        response = self.login(self.client, "hrstaff", "HrPass123")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/hr/home")
        home = self.client.get(response.location)
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"Daily HR tasks", home.get_data())
        self.assertIn(b"Pending leave", home.get_data())
        self.assertEqual(self.client.get("/").location, "/hr/home")
        self.assertEqual(self.client.get("/employee/home").status_code, 403)
        employees = self.client.get("/employees/")
        self.assertEqual(employees.status_code, 200)
        self.assertIn(b"HR Employee Directory", employees.get_data())
        self.assertIn(b"hrstaff@example.test", employees.get_data())
        self.assertNotIn(b"Edit account", employees.get_data())

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

    def test_user_emails_are_masked_and_role_changes_remain_admin_only(self):
        self.login(self.client, "admin", "AdminPass123")
        response = self.client.get("/users/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        email_cells = re.findall(
            r'<span class="user-email-value"[^>]*>([^<]*)</span>',
            html,
        )
        self.assertEqual(len(email_cells), 3)
        self.assertIn("s****@example.test", email_cells)
        self.assertNotIn("staff@example.test", email_cells)
        self.assertEqual(html.count('data-email-toggle'), 3)
        self.assertEqual(html.count('aria-label="Show email"'), 3)
        self.assertIn('data-email="staff@example.test"', html)

        hr_client = self.app.test_client()
        self.login(hr_client, "hrstaff", "HrPass123")
        with hr_client.session_transaction() as session:
            csrf_token = session["_csrf_token"]
        response = hr_client.post(
            f"/users/{self.employee_id}/role",
            data={"_csrf_token": csrf_token, "role": self.User.ADMIN},
        )
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(self.User, self.employee_id).role,
                self.User.EMPLOYEE,
            )

    def test_travel_manage_hides_action_column_and_keeps_approval_actions(self):
        from datetime import date

        with self.app.app_context():
            department = self.Department(department_name="Travel review")
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Travel",
                last_name="Staff",
                position="Analyst",
                salary=50000,
                department=department,
            )
            self.db.session.add(employee)
            self.db.session.flush()
            order = self.TravelOrder(
                employee_id=employee.id,
                destination="Manila",
                purpose="Client meeting",
                departure_date=date(2026, 11, 5),
                return_date=date(2026, 11, 6),
            )
            self.db.session.add(order)
            self.db.session.commit()
            order_id = order.id

        self.login(self.client, "admin", "AdminPass123")
        response = self.client.get("/travel-orders/manage")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        headers = re.search(r"<thead>.*?</thead>", html, re.DOTALL).group(0)
        self.assertNotIn("<th>Action</th>", headers)
        self.assertIn("TO-", html)
        self.assertIn("Approve", html)
        self.assertIn("Decline", html)

        form = self.client.get("/travel-orders/manage")
        response = self.client.post(
            f"/travel-orders/manage/{order_id}/status",
            data={
                "_csrf_token": self.csrf_token(form),
                "status": self.TravelOrder.APPROVED,
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(self.TravelOrder, order_id).status,
                self.TravelOrder.APPROVED,
            )
        self.assertEqual(
            self.client.post(
                f"/travel-orders/manage/{order_id}/status",
                data={
                    "_csrf_token": self.csrf_token(form),
                    "status": self.TravelOrder.DECLINED,
                },
            ).status_code,
            409,
        )

    def test_paid_payroll_is_locked_and_admin_corrections_are_audited(self):
        from datetime import date
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Payroll correction")
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Payroll",
                last_name="Staff",
                position="Analyst",
                salary=Decimal("50000.00"),
                department=department,
            )
            self.db.session.add(employee)
            self.db.session.flush()
            payroll = self.Payroll(
                employee_id=employee.id,
                pay_period_start=date(2026, 10, 1),
                pay_period_end=date(2026, 10, 31),
                basic_salary=Decimal("4000.00"),
                allowances=Decimal("100.00"),
                deductions=Decimal("50.00"),
                net_pay=Decimal("4050.00"),
                payment_date=date(2026, 11, 1),
            )
            self.db.session.add(payroll)
            self.db.session.commit()
            payroll_id = payroll.id
            payroll_employee_id = employee.id

        self.login(self.client, "hrstaff", "HrPass123")
        self.assertEqual(self.client.get(f"/payroll/{payroll_id}/edit").status_code, 409)
        response = self.client.post(
            f"/payroll/{payroll_id}/edit",
            data={
                "_csrf_token": self.csrf_token(self.client.get("/payroll/add")),
                "employee_id": str(payroll_employee_id),
                "pay_period_start": "2026-10-01",
                "pay_period_end": "2026-10-31",
                "payment_date": "2026-11-01",
                "basic_salary": "9999.00",
                "allowances": "100.00",
                "deductions": "50.00",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            self.client.get(f"/payroll/{payroll_id}/correct").status_code,
            403,
        )
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(self.Payroll, payroll_id).net_pay,
                Decimal("4050.00"),
            )
            self.assertEqual(self.RecordAudit.query.count(), 0)

        admin_client = self.app.test_client()
        self.login(admin_client, "admin", "AdminPass123")
        form = admin_client.get(f"/payroll/{payroll_id}/correct")
        self.assertEqual(form.status_code, 200)
        response = admin_client.post(
            f"/payroll/{payroll_id}/correct",
            data={
                "_csrf_token": self.csrf_token(form),
                "employee_id": str(payroll_employee_id),
                "pay_period_start": "2026-10-01",
                "pay_period_end": "2026-10-31",
                "payment_date": "2026-11-01",
                "basic_salary": "4200.00",
                "allowances": "100.00",
                "deductions": "50.00",
                "reason": "Corrected the verified base salary amount.",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            payroll = self.db.session.get(self.Payroll, payroll_id)
            audit = self.RecordAudit.query.filter_by(
                record_type="payroll",
                record_id=payroll_id,
            ).one()
            self.assertEqual(payroll.net_pay, Decimal("4250.00"))
            self.assertEqual(audit.actor_username, "admin")
            self.assertEqual(audit.before_values["net_pay"], "4050.00")
            self.assertEqual(audit.after_values["net_pay"], "4250.00")

    def test_attendance_corrections_and_deletions_are_authorized_and_audited(self):
        from datetime import date, time
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Attendance audit")
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Attendance",
                last_name="Staff",
                position="Analyst",
                salary=Decimal("50000.00"),
                department=department,
            )
            self.db.session.add(employee)
            self.db.session.flush()
            attendance = self.Attendance(
                employee_id=employee.id,
                attendance_date=date(2026, 10, 1),
                time_in=time(9, 0),
                time_out=time(17, 0),
                status="Present",
            )
            self.db.session.add(attendance)
            self.db.session.commit()
            attendance_id = attendance.id
            employee_record_id = employee.id

        employee_client = self.app.test_client()
        self.login(employee_client, "staff", "StaffPass123")
        with employee_client.session_transaction() as session:
            employee_csrf_token = session["_csrf_token"]
        for path in (
            f"/attendance/{attendance_id}/edit",
            f"/attendance/{attendance_id}/delete",
        ):
            response = employee_client.post(
                path,
                data={
                    "_csrf_token": employee_csrf_token,
                    "reason": "Unauthorized record change attempt.",
                    "employee_id": str(employee_record_id),
                    "attendance_date": "2026-10-02",
                    "time_in": "09:00",
                    "time_out": "17:00",
                    "status": "Late",
                },
            )
            self.assertEqual(response.status_code, 403)

        self.login(self.client, "hrstaff", "HrPass123")
        form = self.client.get(f"/attendance/{attendance_id}/edit")
        edit_data = {
            "_csrf_token": self.csrf_token(form),
            "employee_id": str(employee_record_id),
            "attendance_date": "2026-10-02",
            "time_in": "09:15",
            "time_out": "17:00",
            "status": "Late",
        }
        response = self.client.post(
            f"/attendance/{attendance_id}/edit",
            data=edit_data,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(
                self.db.session.get(self.Attendance, attendance_id).status,
                "Present",
            )

        edit_data["reason"] = "Corrected the recorded late arrival."
        response = self.client.post(
            f"/attendance/{attendance_id}/edit",
            data=edit_data,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            audit = self.RecordAudit.query.filter_by(
                record_type="attendance",
                record_id=attendance_id,
            ).one()
            self.assertEqual(audit.actor_username, "hrstaff")
            self.assertEqual(audit.before_values["status"], "Present")
            self.assertEqual(audit.after_values["status"], "Late")

        response = self.client.post(
            f"/attendance/{attendance_id}/delete",
            data={"_csrf_token": edit_data["_csrf_token"]},
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            f"/attendance/{attendance_id}/delete",
            data={
                "_csrf_token": edit_data["_csrf_token"],
                "reason": "Duplicate imported attendance entry.",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNone(self.db.session.get(self.Attendance, attendance_id))
            deletion = self.RecordAudit.query.filter_by(
                record_type="attendance",
                record_id=attendance_id,
                action="deleted",
            ).one()
            self.assertEqual(deletion.before_values["status"], "Late")

    def test_external_post_login_redirect_is_ignored(self):
        path = "/login?next=https://example.invalid/"
        response = self.login(self.client, "admin", "AdminPass123", path)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/")

    def test_static_assets_use_content_versioned_cache_headers(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)

        for filename in ("css/style.css", "js/script.js"):
            with self.subTest(filename=filename):
                escaped_filename = re.escape(filename).encode()
                match = re.search(
                    rb"/static/"
                    + escaped_filename
                    + rb"\?v=([a-f0-9]{64})",
                    response.data,
                )
                self.assertIsNotNone(match)
                asset_response = self.client.get(
                    f"/static/{filename}?v={match.group(1).decode()}"
                )
                self.assertEqual(asset_response.status_code, 200)
                self.assertIn(
                    "max-age=31536000",
                    asset_response.headers["Cache-Control"],
                )
                self.assertIn(
                    "immutable",
                    asset_response.headers["Cache-Control"],
                )
                self.assertNotIn(
                    "no-cache",
                    asset_response.headers["Cache-Control"],
                )
                asset_response.close()

    def test_employee_payslips_are_finalized_owned_and_downloadable(self):
        from datetime import date
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Payslip access")
            self.db.session.add(department)
            self.db.session.flush()
            employees = [
                self.Employee(
                    user_id=user_id,
                    first_name=name,
                    last_name="Staff",
                    position="Analyst",
                    salary=Decimal("50000.00"),
                    department_id=department.id,
                )
                for user_id, name in (
                    (self.employee_id, "Own"),
                    (self.hr_id, "Other"),
                )
            ]
            self.db.session.add_all(employees)
            self.db.session.flush()
            own_payroll = self.Payroll(
                employee_id=employees[0].id,
                pay_period_start=date(2026, 9, 1),
                pay_period_end=date(2026, 9, 30),
                basic_salary=Decimal("4000.00"),
                allowances=Decimal("250.00"),
                deductions=Decimal("100.00"),
                net_pay=Decimal("4150.00"),
                payment_date=date(2026, 10, 1),
            )
            draft_payroll = self.Payroll(
                employee_id=employees[0].id,
                pay_period_start=date(2026, 10, 1),
                pay_period_end=date(2026, 10, 31),
                basic_salary=Decimal("5000.00"),
                allowances=Decimal("0.00"),
                deductions=Decimal("0.00"),
                net_pay=Decimal("5000.00"),
            )
            other_payroll = self.Payroll(
                employee_id=employees[1].id,
                pay_period_start=date(2026, 9, 1),
                pay_period_end=date(2026, 9, 30),
                basic_salary=Decimal("7000.00"),
                allowances=Decimal("0.00"),
                deductions=Decimal("0.00"),
                net_pay=Decimal("7000.00"),
                payment_date=date(2026, 10, 1),
            )
            self.db.session.add_all([own_payroll, draft_payroll, other_payroll])
            employees[0].salary = Decimal("99000.00")
            self.db.session.commit()
            own_id = own_payroll.id
            draft_id = draft_payroll.id
            other_id = other_payroll.id

        self.login(self.client, "staff", "StaffPass123")
        listing = self.client.get("/payslips/")
        self.assertEqual(listing.status_code, 200)
        self.assertIn(b"4150.00", listing.data)
        self.assertNotIn(b"5000.00", listing.data)
        self.assertNotIn(b"7000.00", listing.data)
        self.assertEqual(self.client.get(f"/payslips/{own_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/payslips/{draft_id}").status_code, 404)
        self.assertEqual(self.client.get(f"/payslips/{other_id}").status_code, 404)
        download = self.client.get(f"/payslips/{own_id}/download")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.mimetype, "application/pdf")
        self.assertTrue(download.data.startswith(b"%PDF"))
        self.assertEqual(download.headers["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.get("/payroll/").status_code, 403)
        self.assertEqual(self.client.get("/payroll/add").status_code, 403)
        self.assertEqual(self.client.get("/payslips/manage").status_code, 403)
        self.assertEqual(
            self.client.get(f"/payslips/{other_id}/download").status_code,
            404,
        )

    def test_employee_requests_validate_ownership_and_prevent_pending_duplicates(self):
        from datetime import date
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Payslip requests")
            self.db.session.add(department)
            self.db.session.flush()
            second_user = self.User(
                username="second-staff",
                email="second-staff@example.test",
                password_hash=generate_password_hash("SecondPass123"),
                role=self.User.EMPLOYEE,
            )
            own_employee = self.Employee(
                user_id=self.employee_id,
                first_name="Own",
                last_name="Staff",
                position="Analyst",
                salary=Decimal("50000.00"),
                department_id=department.id,
            )
            other_employee = self.Employee(
                user=second_user,
                first_name="Second",
                last_name="Staff",
                position="Analyst",
                salary=Decimal("50000.00"),
                department=department,
            )
            self.db.session.add_all([own_employee, other_employee])
            self.db.session.flush()
            payrolls = [
                self.Payroll(
                    employee_id=employee.id,
                    pay_period_start=date(2026, 10, 1),
                    pay_period_end=date(2026, 10, 31),
                    basic_salary=Decimal("4000.00"),
                    allowances=Decimal("0.00"),
                    deductions=Decimal("0.00"),
                    net_pay=Decimal("4000.00"),
                )
                for employee in (own_employee, other_employee)
            ]
            self.db.session.add_all(payrolls)
            self.db.session.commit()
            own_employee_id = own_employee.id
            other_employee_id = other_employee.id
            own_payroll_id = payrolls[0].id

        self.login(self.client, "staff", "StaffPass123")
        form = self.client.get("/payslips/requests")
        self.assertEqual(form.status_code, 200)
        response = self.client.post(
            "/payslips/requests",
            data={
                "_csrf_token": self.csrf_token(form),
                "pay_period_start": "2026-10-01",
                "pay_period_end": "2026-10-31",
                "employee_id": str(other_employee_id),
                "reason": "Personal copy",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            linked_request = self.PayslipRequest.query.one()
            self.assertEqual(linked_request.employee_id, own_employee_id)
            self.assertEqual(linked_request.payroll_id, own_payroll_id)

        form = self.client.get("/payslips/requests")
        response = self.client.post(
            "/payslips/requests",
            data={
                "_csrf_token": self.csrf_token(form),
                "pay_period_start": "2026-08-01",
                "pay_period_end": "2026-08-31",
                "reason": "Loan or financial requirement",
                "details": "Bank application",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(self.PayslipRequest.query.count(), 2)
            payslip_request = self.PayslipRequest.query.filter_by(
                pay_period_start=date(2026, 8, 1)
            ).one()
            self.assertEqual(payslip_request.employee_id, own_employee_id)
            self.assertIsNone(payslip_request.payroll_id)
            self.assertEqual(payslip_request.status, "Pending")
            self.assertIsNotNone(payslip_request.request_date)

        form = self.client.get("/payslips/requests")
        duplicate = self.client.post(
            "/payslips/requests",
            data={
                "_csrf_token": self.csrf_token(form),
                "pay_period_start": "2026-08-01",
                "pay_period_end": "2026-08-31",
                "reason": "Other",
            },
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertIn(b"pending request already exists", duplicate.data)
        with self.app.app_context():
            self.assertEqual(self.PayslipRequest.query.count(), 2)

        second_client = self.app.test_client()
        self.login(second_client, "second-staff", "SecondPass123")
        history = second_client.get("/payslips/requests")
        self.assertEqual(history.status_code, 200)
        self.assertNotIn(b"Bank application", history.data)

    def test_hr_reviews_pending_requests_and_employee_sees_remarks(self):
        from datetime import date
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Request review")
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Jamie",
                last_name="Staff",
                position="Analyst",
                salary=Decimal("50000.00"),
                department_id=department.id,
            )
            payslip_request = self.PayslipRequest(
                employee=employee,
                payroll=None,
                pay_period_start=date(2026, 10, 1),
                pay_period_end=date(2026, 10, 31),
                reason="Payslip not received",
            )
            rejected_request = self.PayslipRequest(
                employee=employee,
                payroll=None,
                pay_period_start=date(2026, 9, 1),
                pay_period_end=date(2026, 9, 30),
                reason="Other",
            )
            self.db.session.add_all([employee, payslip_request, rejected_request])
            self.db.session.commit()
            request_id = payslip_request.id
            rejected_request_id = rejected_request.id
            employee_record_id = employee.id

        employee_client = self.app.test_client()
        self.login(employee_client, "staff", "StaffPass123")
        self.assertEqual(
            employee_client.get("/payslips/manage").status_code,
            403,
        )
        self.assertEqual(
            employee_client.get(f"/payslips/manage/{request_id}").status_code,
            403,
        )
        employee_form = employee_client.get("/payslips/requests")
        forbidden_review = employee_client.post(
            f"/payslips/manage/{request_id}",
            data={
                "_csrf_token": self.csrf_token(employee_form),
                "status": "Approved",
            },
        )
        self.assertEqual(forbidden_review.status_code, 403)

        self.login(self.client, "hrstaff", "HrPass123")
        listing = self.client.get("/payslips/manage?status=Pending")
        self.assertEqual(listing.status_code, 200)
        self.assertIn(b"Jamie Staff", listing.data)
        detail = self.client.get(f"/payslips/manage/{request_id}")
        response = self.client.post(
            f"/payslips/manage/{request_id}",
            data={
                "_csrf_token": self.csrf_token(detail),
                "status": "Approved",
                "hr_remarks": "Payroll has not been finalized.",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            pending = self.db.session.get(self.PayslipRequest, request_id)
            self.assertEqual(pending.status, "Pending")

        detail = self.client.get(f"/payslips/manage/{request_id}")
        self.assertIn(b"Create payroll record", detail.data)
        add_form = self.client.get(
            f"/payroll/add?employee_id={employee_record_id}"
            "&pay_period_start=2026-10-01&pay_period_end=2026-10-31"
        )
        self.assertEqual(add_form.status_code, 200)
        self.assertIn(b'value="2026-10-01"', add_form.data)
        response = self.client.post(
            "/payroll/add",
            data={
                "_csrf_token": self.csrf_token(add_form),
                "employee_id": str(employee_record_id),
                "pay_period_start": "2026-10-01",
                "pay_period_end": "2026-10-31",
                "payment_date": "2026-11-05",
                "basic_salary": "4000.00",
                "allowances": "200.00",
                "deductions": "100.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            payroll_id = self.Payroll.query.one().id

        detail = self.client.get(f"/payslips/manage/{request_id}")
        response = self.client.post(
            f"/payslips/manage/{request_id}",
            data={
                "_csrf_token": self.csrf_token(detail),
                "status": "Approved",
                "hr_remarks": "Your finalized payslip is available.",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            reviewed = self.db.session.get(self.PayslipRequest, request_id)
            self.assertEqual(reviewed.status, "Approved")
            self.assertEqual(reviewed.reviewed_by, self.hr_id)
            self.assertIsNotNone(reviewed.reviewed_at)
            self.assertEqual(
                reviewed.hr_remarks,
                "Your finalized payslip is available.",
            )
        stale = self.client.post(
            f"/payslips/manage/{request_id}",
            data={
                "_csrf_token": self.csrf_token(detail),
                "status": "Rejected",
            },
        )
        self.assertEqual(stale.status_code, 409)

        rejection_form = self.client.get(
            f"/payslips/manage/{rejected_request_id}"
        )
        rejected = self.client.post(
            f"/payslips/manage/{rejected_request_id}",
            data={
                "_csrf_token": self.csrf_token(rejection_form),
                "status": "Rejected",
                "hr_remarks": "Please contact HR for more information.",
            },
        )
        self.assertEqual(rejected.status_code, 302)
        with self.app.app_context():
            rejected_record = self.db.session.get(
                self.PayslipRequest,
                rejected_request_id,
            )
            self.assertEqual(rejected_record.status, "Rejected")
            self.assertEqual(rejected_record.reviewed_by, self.hr_id)
            self.assertIsNotNone(rejected_record.reviewed_at)

        history = employee_client.get("/payslips/requests")
        self.assertIn(b"Approved", history.data)
        self.assertIn(b"Rejected", history.data)
        self.assertIn(b"Your finalized payslip is available.", history.data)
        self.assertIn(
            b"Please contact HR for more information.",
            history.data,
        )
        self.assertEqual(
            employee_client.get(f"/payslips/{payroll_id}").status_code,
            200,
        )
        self.assertEqual(
            employee_client.get(f"/payslips/{payroll_id}/download").status_code,
            200,
        )

        admin_client = self.app.test_client()
        self.login(admin_client, "admin", "AdminPass123")
        self.assertEqual(admin_client.get("/payslips/manage").status_code, 200)

    def test_employee_travel_order_submission_validation_and_ownership(self):
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Travel requests")
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Travel",
                last_name="Employee",
                position="Coordinator",
                salary=Decimal("50000.00"),
                department_id=department.id,
            )
            second_user = self.User(
                username="travel-other",
                email="travel-other@example.test",
                password_hash=generate_password_hash("TravelOther123"),
                role=self.User.EMPLOYEE,
            )
            other_employee = self.Employee(
                user=second_user,
                first_name="Other",
                last_name="Employee",
                position="Coordinator",
                salary=Decimal("50000.00"),
                department=department,
            )
            self.db.session.add_all([employee, other_employee])
            self.db.session.commit()
            employee_id = employee.id

        self.login(self.client, "staff", "StaffPass123")
        home = self.client.get("/employee/home")
        self.assertIn(b"My Travel Orders", home.data)
        self.assertIn(b"Submit Travel Order", home.data)

        form = self.client.get("/travel-orders/submit")
        self.assertEqual(form.status_code, 200)
        form_html = form.get_data(as_text=True)
        self.assertIn("Travel Date Range", form_html)
        self.assertIn('name="departure_date"', form_html)
        self.assertIn('name="return_date"', form_html)
        self.assertIn("data-range-required", form_html)
        self.assertEqual(form_html.count('data-date-range'), 1)
        self.assertNotIn('type="date"', form_html)
        incomplete = self.client.post(
            "/travel-orders/submit",
            data={
                "_csrf_token": self.csrf_token(form),
                "destination": "Cebu",
            },
        )
        self.assertEqual(incomplete.status_code, 200)
        self.assertIn(b"Destination and purpose are required", incomplete.data)

        form = self.client.get("/travel-orders/submit")
        invalid_dates = self.client.post(
            "/travel-orders/submit",
            data={
                "_csrf_token": self.csrf_token(form),
                "destination": "Cebu",
                "purpose": "Client meeting",
                "departure_date": "2026-11-10",
                "return_date": "2026-11-09",
            },
        )
        self.assertEqual(invalid_dates.status_code, 200)
        self.assertIn(
            b"Return date cannot be earlier than departure date",
            invalid_dates.data,
        )
        with self.app.app_context():
            self.assertEqual(self.TravelOrder.query.count(), 0)

        form = self.client.get("/travel-orders/submit")
        created = self.client.post(
            "/travel-orders/submit",
            data={
                "_csrf_token": self.csrf_token(form),
                "employee_id": "999999",
                "destination": "Cebu",
                "purpose": "Client meeting",
                "departure_date": "2026-11-10",
                "return_date": "2026-11-12",
            },
        )
        self.assertEqual(created.status_code, 302)
        with self.app.app_context():
            order = self.TravelOrder.query.one()
            order_id = order.id
            self.assertEqual(order.employee_id, employee_id)
            self.assertEqual(str(order.departure_date), "2026-11-10")
            self.assertEqual(str(order.return_date), "2026-11-12")
            self.assertEqual(order.status, self.TravelOrder.PENDING)
            self.assertIsNotNone(order.created_at)

        listing = self.client.get("/travel-orders/")
        self.assertEqual(listing.status_code, 200)
        self.assertIn(b"Cebu", listing.data)
        self.assertIn(b"Pending", listing.data)
        other_client = self.app.test_client()
        self.login(other_client, "travel-other", "TravelOther123")
        self.assertNotIn(b"Cebu", other_client.get("/travel-orders/").data)
        self.assertEqual(other_client.get("/travel-orders/submit").status_code, 200)
        self.assertEqual(self.client.get("/travel-orders/manage").status_code, 403)
        self.assertEqual(
            self.client.post(
                f"/travel-orders/manage/{order_id}/status",
                data={
                    "_csrf_token": self.csrf_token(listing),
                    "status": "Approved",
                },
            ).status_code,
            403,
        )

    def test_hr_and_admin_can_review_only_pending_travel_orders(self):
        from datetime import date
        from decimal import Decimal

        with self.app.app_context():
            department = self.Department(department_name="Travel review")
            self.db.session.add(department)
            self.db.session.flush()
            employee = self.Employee(
                user_id=self.employee_id,
                first_name="Travel",
                last_name="Requester",
                position="Analyst",
                salary=Decimal("50000.00"),
                department_id=department.id,
            )
            approved_order = self.TravelOrder(
                employee=employee,
                destination="Manila",
                purpose="Conference",
                departure_date=date(2026, 12, 1),
                return_date=date(2026, 12, 3),
            )
            declined_order = self.TravelOrder(
                employee=employee,
                destination="Davao",
                purpose="Site visit",
                departure_date=date(2026, 12, 5),
                return_date=date(2026, 12, 6),
            )
            self.db.session.add_all([employee, approved_order, declined_order])
            self.db.session.commit()
            approved_id = approved_order.id
            declined_id = declined_order.id

        self.login(self.client, "hrstaff", "HrPass123")
        pending_page = self.client.get("/travel-orders/manage?status=Pending")
        self.assertEqual(pending_page.status_code, 200)
        self.assertIn(b"Manila", pending_page.data)
        self.assertIn(b"Davao", pending_page.data)
        response = self.client.post(
            f"/travel-orders/manage/{approved_id}/status",
            data={
                "_csrf_token": self.csrf_token(pending_page),
                "status": "Approved",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            order = self.db.session.get(self.TravelOrder, approved_id)
            self.assertEqual(order.status, self.TravelOrder.APPROVED)
            self.assertEqual(order.approved_by, self.hr_id)
            self.assertIsNotNone(order.approval_date)

        stale = self.client.post(
            f"/travel-orders/manage/{approved_id}/status",
            data={
                "_csrf_token": self.csrf_token(pending_page),
                "status": "Declined",
            },
        )
        self.assertEqual(stale.status_code, 409)
        approved_page = self.client.get("/travel-orders/manage?status=Approved")
        self.assertIn(b"Manila", approved_page.data)
        self.assertNotIn(b"Davao", approved_page.data)

        admin_client = self.app.test_client()
        self.login(admin_client, "admin", "AdminPass123")
        admin_page = admin_client.get("/travel-orders/manage")
        self.assertEqual(admin_page.status_code, 200)
        declined = admin_client.post(
            f"/travel-orders/manage/{declined_id}/status",
            data={
                "_csrf_token": self.csrf_token(admin_page),
                "status": "Declined",
            },
        )
        self.assertEqual(declined.status_code, 302)
        with self.app.app_context():
            order = self.db.session.get(self.TravelOrder, declined_id)
            self.assertEqual(order.status, self.TravelOrder.DECLINED)
            self.assertEqual(order.approved_by, self.admin_id)
            self.assertIsNotNone(order.approval_date)

if __name__ == "__main__":
    unittest.main()
