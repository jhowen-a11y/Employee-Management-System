import base64
import os
import re
import unittest
import zlib
from datetime import date, time
from decimal import Decimal
from unittest.mock import patch

from werkzeug.security import generate_password_hash


class PayrollDeductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = patch.dict(
            os.environ,
            {
                "SECRET_KEY": "payroll-deduction-tests",
                "DATABASE_URL": "postgresql://test:test@localhost/test",
            },
        )
        cls.environment.start()

        from app import create_app
        from models import db
        from models.attendance import Attendance
        from models.department import Department
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
            {
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "TESTING": True,
                "PAYROLL_MONTHLY_WORKING_DAYS": "22",
                "PAYROLL_HOURS_PER_DAY": "8",
                "PAYROLL_SHIFT_START": "08:00",
                "PAYROLL_LATE_GRACE_MINUTES": "0",
                "PAYROLL_NON_WORKING_DATES": "2026-11-05",
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
            department = self.Department(department_name="Payroll Tests")
            admin = self.User(
                username="payroll-admin",
                email="payroll-admin@example.test",
                password_hash=generate_password_hash("AdminPass123"),
                role=self.User.ADMIN,
            )
            employee_user = self.User(
                username="payroll-employee",
                email="payroll-employee@example.test",
                password_hash=generate_password_hash("EmployeePass123"),
                role=self.User.EMPLOYEE,
            )
            self.db.session.add_all([department, admin, employee_user])
            self.db.session.flush()
            employee = self.Employee(
                user=employee_user,
                first_name="Sample",
                last_name="Employee",
                position="Analyst",
                salary=Decimal("22000.00"),
                department=department,
            )
            self.db.session.add(employee)
            self.db.session.commit()
            self.employee_id = employee.id
            self.admin_id = admin.id
            self.employee_user_id = employee_user.id
        self.client = self.app.test_client()

    @staticmethod
    def csrf_token(response):
        match = re.search(
            r'name="_csrf_token" value="([^"]+)"',
            response.get_data(as_text=True),
        )
        if match is None:
            raise AssertionError("Payroll form does not include a CSRF token.")
        return match.group(1)

    def login_as(self, user_id):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True

    def add_attendance(self, day, status, time_in=None):
        self.db.session.add(
            self.Attendance(
                employee_id=self.employee_id,
                attendance_date=day,
                status=status,
                time_in=time_in,
            )
        )

    def test_calculates_only_explicit_absences_and_deduplicates_late_days(self):
        from services.payroll_deductions import calculate_attendance_deductions

        with self.app.app_context():
            self.add_attendance(date(2026, 11, 2), "Absent")
            self.add_attendance(date(2026, 11, 3), "Late", time(8, 30))
            self.add_attendance(date(2026, 11, 3), "Late", time(9, 0))
            self.add_attendance(date(2026, 11, 4), "Absent")
            self.add_attendance(date(2026, 11, 5), "Absent")
            self.add_attendance(date(2026, 11, 6), "Late")
            self.db.session.add(
                self.Leave(
                    employee_id=self.employee_id,
                    leave_type="Annual",
                    start_date=date(2026, 11, 4),
                    end_date=date(2026, 11, 4),
                    status="Approved",
                )
            )
            self.db.session.commit()

            calculation = calculate_attendance_deductions(
                self.employee_id,
                date(2026, 11, 2),
                date(2026, 11, 8),
                Decimal("22000.00"),
            )

        self.assertEqual(calculation["daily_rate"], Decimal("1000.00"))
        self.assertEqual(calculation["hourly_rate"], Decimal("125.00"))
        self.assertEqual(calculation["absence_days"], 1)
        self.assertEqual(calculation["absence_deduction"], Decimal("1000.00"))
        self.assertEqual(calculation["late_minutes"], 60)
        self.assertEqual(calculation["late_occurrences"], 1)
        self.assertEqual(calculation["late_deduction"], Decimal("125.00"))
        self.assertEqual(calculation["total_deductions"], Decimal("1125.00"))
        self.assertEqual(calculation["incomplete_attendance_days"], 1)

    def test_missing_attendance_and_weekend_absences_are_not_deducted(self):
        from services.payroll_deductions import calculate_attendance_deductions

        with self.app.app_context():
            self.add_attendance(date(2026, 11, 7), "Absent")
            self.db.session.commit()
            calculation = calculate_attendance_deductions(
                self.employee_id,
                date(2026, 11, 2),
                date(2026, 11, 8),
                Decimal("22000.00"),
            )
        self.assertEqual(calculation["absence_days"], 0)
        self.assertEqual(calculation["late_minutes"], 0)

    def test_multiple_explicit_absences_each_use_the_daily_rate(self):
        from services.payroll_deductions import calculate_attendance_deductions

        with self.app.app_context():
            self.add_attendance(date(2026, 11, 2), "Absent")
            self.add_attendance(date(2026, 11, 3), "Absent")
            self.db.session.commit()
            calculation = calculate_attendance_deductions(
                self.employee_id,
                date(2026, 11, 2),
                date(2026, 11, 6),
                Decimal("22000.00"),
            )
        self.assertEqual(calculation["absence_days"], 2)
        self.assertEqual(calculation["absence_deduction"], Decimal("2000.00"))

    def test_preview_and_payroll_creation_ignore_submitted_deduction_amount(self):
        self.login_as(self.admin_id)
        with self.app.app_context():
            self.add_attendance(date(2026, 11, 2), "Absent")
            self.add_attendance(date(2026, 11, 3), "Late", time(8, 30))
            self.db.session.commit()

        preview = self.client.get(
            "/payroll/deduction-preview",
            query_string={
                "employee_id": self.employee_id,
                "pay_period_start": "2026-11-02",
                "pay_period_end": "2026-11-30",
                "basic_salary": "22000.00",
                "allowances": "100.00",
            },
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json["absence_days"], 1)
        self.assertEqual(preview.json["late_minutes"], 30)
        self.assertEqual(preview.json["late_occurrences"], 1)
        self.assertEqual(preview.json["total_deductions"], "1062.50")
        self.assertEqual(preview.json["estimated_net_pay"], "21037.50")

        form = self.client.get("/payroll/add")
        self.assertIn(b"Attendance deduction preview", form.data)
        self.assertNotIn(b'name="deductions"', form.data)
        response = self.client.post(
            "/payroll/add",
            data={
                "_csrf_token": self.csrf_token(form),
                "employee_id": str(self.employee_id),
                "pay_period_start": "2026-11-02",
                "pay_period_end": "2026-11-30",
                "basic_salary": "22000.00",
                "allowances": "100.00",
                "deductions": "0.01",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            payroll = self.Payroll.query.one()
            payroll_id = payroll.id
            self.assertEqual(payroll.absence_days, 1)
            self.assertEqual(payroll.late_minutes, 30)
            self.assertEqual(payroll.late_occurrences, 1)
            self.assertEqual(payroll.absence_deduction, Decimal("1000.00"))
            self.assertEqual(payroll.late_deduction, Decimal("62.50"))
            self.assertEqual(payroll.deductions, Decimal("1062.50"))
            self.assertEqual(payroll.net_pay, Decimal("21037.50"))

            self.add_attendance(date(2026, 11, 2), "Present", time(8, 0))
            self.db.session.commit()
            self.db.session.expire_all()
            payroll = self.db.session.get(self.Payroll, payroll_id)
            self.assertEqual(payroll.deductions, Decimal("1062.50"))
            self.assertEqual(payroll.absence_deduction, Decimal("1000.00"))

        admin_detail = self.client.get(f"/payroll/{payroll_id}")
        self.assertIn(b"Absences", admin_detail.data)
        self.assertIn(b"1 day", admin_detail.data)
        self.assertIn(b"1 occurrence (30 minutes)", admin_detail.data)
        self.assertIn(b"Total deductions", admin_detail.data)
        self.assertIn(b"1,062.50", admin_detail.data)
        self.assertIn(b"1062.50", self.client.get("/payroll/").data)
        with self.app.app_context():
            payroll = self.db.session.get(self.Payroll, payroll_id)
            payroll.payment_date = date(2026, 12, 1)
            self.db.session.commit()
        self.assertEqual(
            self.client.get(f"/payroll/{payroll_id}/edit").status_code,
            409,
        )

        self.login_as(self.employee_user_id)
        payslip = self.client.get(f"/payslips/{payroll_id}")
        self.assertEqual(payslip.status_code, 200)
        self.assertIn(b"Absences (1 day)", payslip.data)
        self.assertIn(b"Lateness (1 occurrence, 30 minutes)", payslip.data)
        self.assertIn(b"Total deductions", payslip.data)
        self.assertIn(b"1,062.50", payslip.data)
        self.assertIn(b"@media print", payslip.data)
        pdf = self.client.get(f"/payslips/{payroll_id}/download")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        pdf_streams = re.findall(
            rb"stream\r?\n(.*?)~?>endstream", pdf.data, re.DOTALL
        )
        pdf_text = b"".join(
            zlib.decompress(
                base64.a85decode(stream.replace(b"~>", b""))
            )
            for stream in pdf_streams
        ).replace(b"\\(", b"(").replace(b"\\)", b")")
        self.assertIn(b"Absences (1 day)", pdf_text)
        self.assertIn(b"Lateness (1 occurrence, 30 minutes)", pdf_text)
        self.assertIn(b"Total deductions", pdf_text)

        self.login_as(self.admin_id)
        pending_form = self.client.get("/payroll/add")
        pending = self.client.post(
            "/payroll/add",
            data={
                "_csrf_token": self.csrf_token(pending_form),
                "employee_id": str(self.employee_id),
                "pay_period_start": "2026-12-01",
                "pay_period_end": "2026-12-31",
                "basic_salary": "22000.00",
                "allowances": "0",
            },
        )
        self.assertEqual(pending.status_code, 302)
        with self.app.app_context():
            pending_record = self.Payroll.query.filter_by(
                pay_period_start=date(2026, 12, 1)
            ).one()
            self.assertIsNone(pending_record.payment_date)
            self.assertEqual(pending_record.deductions, Decimal("0.00"))

        duplicate_form = self.client.get("/payroll/add")
        duplicate = self.client.post(
            "/payroll/add",
            data={
                "_csrf_token": self.csrf_token(duplicate_form),
                "employee_id": str(self.employee_id),
                "pay_period_start": "2026-11-02",
                "pay_period_end": "2026-11-30",
                "basic_salary": "22000.00",
                "allowances": "0",
            },
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertIn(b"already exists", duplicate.data)

    def test_only_management_can_preview_another_employees_calculation(self):
        self.login_as(self.employee_user_id)
        response = self.client.get(
            "/payroll/deduction-preview",
            query_string={
                "employee_id": self.employee_id,
                "pay_period_start": "2026-11-01",
                "pay_period_end": "2026-11-30",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_historical_manual_deductions_remain_without_fabricated_breakdown(self):
        with self.app.app_context():
            historical = self.Payroll(
                employee_id=self.employee_id,
                pay_period_start=date(2026, 10, 1),
                pay_period_end=date(2026, 10, 31),
                basic_salary=Decimal("22000.00"),
                allowances=Decimal("100.00"),
                deductions=Decimal("75.00"),
                net_pay=Decimal("22025.00"),
            )
            self.db.session.add(historical)
            self.db.session.commit()
            payroll_id = historical.id

        self.login_as(self.admin_id)
        response = self.client.get(f"/payroll/{payroll_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Unavailable for this historical payroll record", response.data)
        with self.app.app_context():
            historical = self.db.session.get(self.Payroll, payroll_id)
            self.assertEqual(historical.deductions, Decimal("75.00"))
            self.assertIsNone(historical.absence_deduction)
            self.assertIsNone(historical.late_deduction)

    def test_historical_breakdown_is_reconstructed_only_when_total_matches(self):
        with self.app.app_context():
            self.add_attendance(date(2026, 10, 5), "Absent")
            self.add_attendance(date(2026, 10, 6), "Late", time(8, 30))
            self.db.session.commit()
            historical = self.Payroll(
                employee_id=self.employee_id,
                pay_period_start=date(2026, 10, 1),
                pay_period_end=date(2026, 10, 31),
                basic_salary=Decimal("22000.00"),
                allowances=Decimal("0.00"),
                deductions=Decimal("1062.50"),
                net_pay=Decimal("20937.50"),
                payment_date=date(2026, 11, 1),
            )
            self.db.session.add(historical)
            self.db.session.commit()
            payroll_id = historical.id
            original_amounts = (
                historical.basic_salary,
                historical.allowances,
                historical.deductions,
                historical.net_pay,
            )

        self.login_as(self.admin_id)
        admin_detail = self.client.get(f"/payroll/{payroll_id}")
        self.assertEqual(admin_detail.status_code, 200)
        self.assertIn(b"Absences", admin_detail.data)
        self.assertIn(b"1 day", admin_detail.data)
        self.assertIn(b"1 occurrence (30 minutes)", admin_detail.data)
        self.assertIn(b"1,062.50", admin_detail.data)

        self.login_as(self.employee_user_id)
        employee_detail = self.client.get(f"/payslips/{payroll_id}")
        self.assertEqual(employee_detail.status_code, 200)
        self.assertIn(b"Lateness (1 occurrence, 30 minutes)", employee_detail.data)
        with self.app.app_context():
            historical = self.db.session.get(self.Payroll, payroll_id)
            self.assertEqual(
                (
                    historical.basic_salary,
                    historical.allowances,
                    historical.deductions,
                    historical.net_pay,
                ),
                original_amounts,
            )

    def test_legacy_breakdown_snapshot_recovers_late_occurrences_safely(self):
        with self.app.app_context():
            self.add_attendance(date(2026, 10, 5), "Absent")
            self.add_attendance(date(2026, 10, 6), "Late", time(8, 30))
            self.db.session.commit()
            historical = self.Payroll(
                employee_id=self.employee_id,
                pay_period_start=date(2026, 10, 1),
                pay_period_end=date(2026, 10, 31),
                basic_salary=Decimal("22000.00"),
                allowances=Decimal("0.00"),
                deductions=Decimal("1062.50"),
                net_pay=Decimal("20937.50"),
                payment_date=date(2026, 11, 1),
                absence_days=1,
                late_minutes=30,
                absence_deduction=Decimal("1000.00"),
                late_deduction=Decimal("62.50"),
            )
            self.db.session.add(historical)
            self.db.session.commit()
            payroll_id = historical.id

        self.login_as(self.employee_user_id)
        detail = self.client.get(f"/payslips/{payroll_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Lateness (1 occurrence, 30 minutes)", detail.data)
        with self.app.app_context():
            historical = self.db.session.get(self.Payroll, payroll_id)
            self.assertIsNone(historical.late_occurrences)

    def test_payroll_pages_remain_available_before_breakdown_migration(self):
        with self.app.app_context():
            self.add_attendance(date(2026, 12, 1), "Absent")
            payroll = self.Payroll(
                employee_id=self.employee_id,
                pay_period_start=date(2026, 10, 1),
                pay_period_end=date(2026, 10, 31),
                basic_salary=Decimal("22000.00"),
                allowances=Decimal("100.00"),
                deductions=Decimal("75.00"),
                net_pay=Decimal("22025.00"),
                payment_date=date(2026, 11, 1),
            )
            self.db.session.add(payroll)
            self.db.session.commit()
            payroll_id = payroll.id
            self.db.session.remove()
            with self.db.engine.begin() as connection:
                for column_name in (
                    "absence_days",
                    "late_minutes",
                    "late_occurrences",
                    "absence_deduction",
                    "late_deduction",
                ):
                    connection.exec_driver_sql(
                        f'ALTER TABLE payroll DROP COLUMN "{column_name}"'
                    )

        self.login_as(self.admin_id)
        for path in (
            "/payroll/",
            "/payroll/?q=Sample&from=2026-10-01&to=2026-10-31&status=paid&sort=net&direction=asc",
            f"/payroll/{payroll_id}",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(b"Page unavailable", response.data)

        add_form = self.client.get("/payroll/add")
        self.assertEqual(add_form.status_code, 200)
        self.assertIn(b"Database update pending", add_form.data)
        response = self.client.post(
            "/payroll/add",
            data={
                "_csrf_token": self.csrf_token(add_form),
                "employee_id": str(self.employee_id),
                "pay_period_start": "2026-12-01",
                "pay_period_end": "2026-12-31",
                "basic_salary": "22000.00",
                "allowances": "100.00",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Payroll was not created", response.data)
        with self.app.app_context():
            created = self.Payroll.query.filter_by(
                pay_period_start=date(2026, 12, 1)
            ).first()
            self.assertIsNone(created)

        with self.app.app_context():
            paid_record = self.db.session.get(self.Payroll, payroll_id)
            original_values = (
                paid_record.employee_id,
                paid_record.pay_period_start,
                paid_record.pay_period_end,
                paid_record.basic_salary,
                paid_record.allowances,
                paid_record.deductions,
                paid_record.net_pay,
                paid_record.payment_date,
            )
        self.assertEqual(
            self.client.get(f"/payroll/{payroll_id}/edit").status_code,
            409,
        )

        self.login_as(self.employee_user_id)
        payslips = self.client.get("/payslips/")
        detail = self.client.get(f"/payslips/{payroll_id}")
        self.assertEqual(payslips.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"75.00", detail.data)
        with self.app.app_context():
            paid_record = self.db.session.get(self.Payroll, payroll_id)
            self.assertEqual(
                (
                    paid_record.employee_id,
                    paid_record.pay_period_start,
                    paid_record.pay_period_end,
                    paid_record.basic_salary,
                    paid_record.allowances,
                    paid_record.deductions,
                    paid_record.net_pay,
                    paid_record.payment_date,
                ),
                original_values,
            )


if __name__ == "__main__":
    unittest.main()
