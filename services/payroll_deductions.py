from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import current_app, g, has_request_context
from sqlalchemy import inspect

from models import db
from models.attendance import Attendance
from models.leave import Leave


CENT = Decimal("0.01")
BREAKDOWN_COLUMNS = {
    "absence_days",
    "late_minutes",
    "absence_deduction",
    "late_deduction",
}


def attendance_deduction_schema_available():
    cache_key = "_payroll_deduction_schema_available"
    if has_request_context() and hasattr(g, cache_key):
        return getattr(g, cache_key)

    column_names = {
        column["name"] for column in inspect(db.engine).get_columns("payroll")
    }
    available = BREAKDOWN_COLUMNS.issubset(column_names)
    if has_request_context():
        setattr(g, cache_key, available)
    return available


def _money(amount):
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def payroll_schedule():
    config = current_app.config
    try:
        monthly_working_days = int(config.get("PAYROLL_MONTHLY_WORKING_DAYS", 22))
        hours_per_day = Decimal(str(config.get("PAYROLL_HOURS_PER_DAY", "8")))
        shift_start = time.fromisoformat(
            str(config.get("PAYROLL_SHIFT_START", "08:00"))
        )
        grace_minutes = int(config.get("PAYROLL_LATE_GRACE_MINUTES", 0))
        holiday_values = config.get("PAYROLL_NON_WORKING_DATES") or ""
        holidays = {
            date.fromisoformat(value.strip())
            for value in str(holiday_values).split(",")
            if value.strip()
        }
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Payroll work schedule configuration is invalid.") from error

    if (
        monthly_working_days < 1
        or monthly_working_days > 31
        or not hours_per_day.is_finite()
        or hours_per_day <= 0
        or hours_per_day > 24
        or shift_start.tzinfo is not None
        or grace_minutes < 0
        or grace_minutes > 1440
    ):
        raise ValueError("Payroll work schedule configuration is invalid.")

    return monthly_working_days, hours_per_day, shift_start, grace_minutes, holidays


def calculate_attendance_deductions(
    employee_id,
    period_start,
    period_end,
    basic_salary,
):
    monthly_days, hours_per_day, shift_start, grace_minutes, holidays = (
        payroll_schedule()
    )
    daily_rate = _money(basic_salary / Decimal(monthly_days))
    hourly_rate = _money(daily_rate / hours_per_day)

    attendance_records = (
        Attendance.query.filter(
            Attendance.employee_id == employee_id,
            Attendance.attendance_date >= period_start,
            Attendance.attendance_date <= period_end,
        )
        .order_by(Attendance.attendance_date, Attendance.id)
        .all()
    )
    attendance_by_date = defaultdict(list)
    for record in attendance_records:
        attendance_by_date[record.attendance_date].append(record)

    approved_leaves = Leave.query.filter(
        Leave.employee_id == employee_id,
        Leave.status == "Approved",
        Leave.start_date <= period_end,
        Leave.end_date >= period_start,
    ).all()

    def is_approved_leave(day):
        return any(
            leave.start_date <= day <= leave.end_date for leave in approved_leaves
        )

    absence_days = 0
    late_minutes = 0
    incomplete_attendance_days = 0
    current_day = period_start
    while current_day <= period_end:
        day_records = attendance_by_date.get(current_day, [])
        scheduled_day = current_day.weekday() < 5 and current_day not in holidays
        if scheduled_day and not is_approved_leave(current_day):
            statuses = {record.status for record in day_records}
            if day_records and statuses == {"Absent"}:
                absence_days += 1
            elif statuses == {"Late"}:
                recorded_minutes = []
                for record in day_records:
                    if record.status != "Late" or record.time_in is None:
                        continue
                    arrived = datetime.combine(current_day, record.time_in)
                    scheduled_start = datetime.combine(current_day, shift_start)
                    minutes_late = max(
                        0,
                        int((arrived - scheduled_start).total_seconds() // 60)
                        - grace_minutes,
                    )
                    recorded_minutes.append(minutes_late)
                if recorded_minutes:
                    late_minutes += max(recorded_minutes)
                else:
                    incomplete_attendance_days += 1
            elif len(statuses) > 1 and statuses.intersection(
                {"Absent", "Late", "On Leave"}
            ):
                incomplete_attendance_days += 1
        current_day += timedelta(days=1)

    absence_deduction = _money(daily_rate * absence_days)
    late_deduction = _money(
        hourly_rate * Decimal(late_minutes) / Decimal(60)
    )
    total_deductions = _money(absence_deduction + late_deduction)
    return {
        "daily_rate": daily_rate,
        "hourly_rate": hourly_rate,
        "absence_days": absence_days,
        "absence_deduction": absence_deduction,
        "late_minutes": late_minutes,
        "late_hours": (Decimal(late_minutes) / Decimal(60)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ),
        "late_deduction": late_deduction,
        "total_deductions": total_deductions,
        "incomplete_attendance_days": incomplete_attendance_days,
    }


def serialize_deduction_preview(calculation, basic_salary, allowances):
    return {
        key: str(value) if isinstance(value, Decimal) else value
        for key, value in {
            **calculation,
            "estimated_net_pay": _money(
                basic_salary + allowances - calculation["total_deductions"]
            ),
        }.items()
    }
