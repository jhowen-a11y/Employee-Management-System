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
        from models.attendance import Attendance
        from models.department import Department
        from models import db
        from models.employee import Employee
        from models.leave import Leave
        from models.payroll import Payroll
        from models.user import User

        cls.db = db
        cls.Attendance = Attendance
        cls.Department = Department
        cls.Employee = Employee
        cls.Leave = Leave
        cls.Payroll = Payroll
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
                department_name="Engineering"
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
            "/leaves/add",
            "/payroll/",
            "/payroll/add",
            "/users/",
            "/users/add",
            "/users/profile",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

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
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            attendance = self.db.session.get(self.Attendance, attendance_id)
            self.assertEqual(attendance.status, "Late")

        response = self.client.post(
            "/leaves/add",
            data={
                "_csrf_token": token,
                "employee_id": str(employee_id),
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

        response = self.client.post(
            "/payroll/add",
            data={
                "_csrf_token": token,
                "employee_id": str(employee_id),
                "pay_period_start": "2026-10-01",
                "pay_period_end": "2026-10-15",
                "payment_date": "2026-10-16",
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
                "payment_date": "2026-10-17",
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
                "payment_date": "2026-10-17",
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
            response = self.client.post(path, data={"_csrf_token": token})
            with self.subTest(path=path):
                self.assertEqual(response.status_code, 302)

        self.client.get("/users/")
        user_response = self.client.post(
            f"/users/{employee_user_id}/role",
            data={"_csrf_token": token, "role": self.User.HR},
        )
        self.assertEqual(user_response.status_code, 302)

    def test_hr_can_manage_hr_records_but_not_accounts_or_employee_profiles(self):
        self.login(self.client, "hrstaff", "HrPass123")
        for path in (
            "/attendance/add",
            "/departments/add",
            "/leaves/add",
            "/payroll/add",
            "/employees/",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        for path in (
            "/employees/add",
            "/users/",
            "/users/add",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)

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
            "/payroll/",
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
        self.assertIn(b"Edit Profile", response.get_data())
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
                department_name="Operations"
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
        self.assertIn(b"Operations", form.get_data())
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
                rb"<strong>(\d+)</strong><span>Accounts \(all roles\)</span>",
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
            )
            other_payroll = self.Payroll(
                employee=other_employee,
                pay_period_start=date(2026, 9, 1),
                pay_period_end=date(2026, 9, 30),
                basic_salary=Decimal("7000.00"),
                allowances=Decimal("0.00"),
                deductions=Decimal("0.00"),
                net_pay=Decimal("7000.00"),
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
        self.assertIn(b"Engineering", home.get_data())
        self.assertIn(b"5000.00", home.get_data())
        self.assertIn(b"My Department", home.get_data())
        self.assertIn(b"My Attendance", home.get_data())
        self.assertIn(b"My Payroll", home.get_data())
        self.assertIn(b"Edit Profile", home.get_data())
        self.assertNotIn(b"Users &amp; Roles", home.get_data())
        self.assertNotIn(b">Employees<", home.get_data())
        self.assertNotIn(b"Finance", home.get_data())
        self.assertNotIn(b"7000.00", home.get_data())
        own_routes = (
            f"/employees/{own_employee_id}",
            f"/departments/{own_department_id}",
            f"/attendance/{own_attendance_id}",
            f"/leaves/{own_leave_id}",
            f"/payroll/{own_payroll_id}",
        )
        other_routes = (
            f"/employees/{other_employee_id}",
            f"/departments/{other_department_id}",
            f"/attendance/{other_attendance_id}",
            f"/leaves/{other_leave_id}",
            f"/payroll/{other_payroll_id}",
        )
        for path in own_routes:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        for path in other_routes:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

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
        self.assertNotIn(
            b"Edit payroll",
            self.client.get(f"/payroll/{own_payroll_id}").get_data(),
        )
        self.assertNotIn(
            b">Edit</a>",
            self.client.get("/payroll/").get_data(),
        )
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
        self.assertIn(b'class="profile-initials"', profile.get_data())
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
        self.assertNotIn(b"Edit</a>", employees.get_data())

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
