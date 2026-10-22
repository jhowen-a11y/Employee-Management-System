import unittest

from sqlalchemy import create_mock_engine

from models import db
from models.travel_order import TravelOrder


class PostgreSQLSchemaTests(unittest.TestCase):
    def test_all_models_compile_for_postgresql(self):
        statements = []
        engine = create_mock_engine(
            "postgresql+psycopg://",
            lambda statement, *args, **kwargs: statements.append(
                str(statement.compile(dialect=engine.dialect))
            ),
        )

        db.metadata.create_all(engine)

        create_statements = "\n".join(statements)
        for table in (
            "users",
            "employees",
            "departments",
            "attendance",
            "leaves",
            "payroll",
            "payslip_requests",
            "travel_orders",
        ):
            with self.subTest(table=table):
                self.assertIn(f"CREATE TABLE {table}", create_statements)

        for index in (
            "ix_attendance_date_id",
            "ix_attendance_employee_date_id",
            "ix_attendance_date_status",
            "ix_leaves_created_id",
            "ix_leaves_employee_created_id",
            "ix_leaves_status",
            "ix_payroll_period_id",
            "ix_payroll_employee_period_id",
            "ix_payslip_requests_status_date",
            "uq_payslip_requests_pending_employee_pay_period",
            "ix_travel_orders_status_created",
            "ix_travel_orders_employee_created",
        ):
            with self.subTest(index=index):
                statement = (
                    f"CREATE UNIQUE INDEX {index}"
                    if index == "uq_payslip_requests_pending_employee_pay_period"
                    else f"CREATE INDEX {index}"
                )
                self.assertIn(statement, create_statements)


if __name__ == "__main__":
    unittest.main()
