from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import current_app, g, has_request_context
from sqlalchemy import inspect, or_

from models import db
from models.attendance import Attendance
from models.leave import Leave
from models.payroll import Payroll
from models.record_audit import RecordAudit


CENT = Decimal("0.01")
BREAKDOWN_COLUMNS = {
    "absence_days",
    "late_minutes",
    "late_occurrences",
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
    late_occurrences = 0
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
                    late_occurrences += 1
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
        "late_occurrences": late_occurrences,
        "late_hours": (Decimal(late_minutes) / Decimal(60)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ),
        "late_deduction": late_deduction,
        "total_deductions": total_deductions,
        "incomplete_attendance_days": incomplete_attendance_days,
    }


def _attendance_history_is_unchanged(payroll):
    if not payroll.created_at:
        return False

    later_payroll_audit = RecordAudit.query.filter(
        RecordAudit.record_type == "payroll",
        RecordAudit.record_id == payroll.id,
        RecordAudit.created_at >= payroll.created_at,
    ).first()
    if later_payroll_audit:
        return False

    later_attendance = Attendance.query.filter(
        Attendance.employee_id == payroll.employee_id,
        Attendance.attendance_date >= payroll.pay_period_start,
        Attendance.attendance_date <= payroll.pay_period_end,
        Attendance.created_at >= payroll.created_at,
    ).first()
    if later_attendance:
        return False

    later_leave = Leave.query.filter(
        Leave.employee_id == payroll.employee_id,
        Leave.start_date <= payroll.pay_period_end,
        Leave.end_date >= payroll.pay_period_start,
        or_(
            Leave.created_at >= payroll.created_at,
            Leave.updated_at >= payroll.created_at,
        ),
    ).first()
    if later_leave:
        return False

    later_audits = RecordAudit.query.filter(
        RecordAudit.record_type.in_(("attendance", "leave")),
        RecordAudit.created_at >= payroll.created_at,
    ).all()
    for audit in later_audits:
        for values in (audit.before_values, audit.after_values):
            if values.get("employee_id") != payroll.employee_id:
                continue
            attendance_date = values.get("attendance_date")
            if attendance_date:
                try:
                    attendance_date = date.fromisoformat(attendance_date)
                except (TypeError, ValueError):
                    return False
                if payroll.pay_period_start <= attendance_date <= payroll.pay_period_end:
                    return False
            elif audit.record_type == "leave":
                return False
    return True


def payroll_deduction_breakdown(payroll):
    if not attendance_deduction_schema_available():
        return None

    absence_days = payroll.absence_days
    late_minutes = payroll.late_minutes
    late_occurrences = payroll.late_occurrences
    absence_amount = payroll.absence_deduction
    late_amount = payroll.late_deduction

    if all(
        value is not None
        for value in (
            absence_days,
            late_minutes,
            late_occurrences,
            absence_amount,
            late_amount,
        )
    ):
        if (
            absence_days < 0
            or late_minutes < 0
            or late_occurrences < 0
            or absence_amount < 0
            or late_amount < 0
            or absence_amount + late_amount != payroll.deductions
        ):
            return None
        return {
            "absence_days": absence_days,
            "absence_deduction": absence_amount,
            "late_minutes": late_minutes,
            "late_occurrences": late_occurrences,
            "late_deduction": late_amount,
            "total_deductions": payroll.deductions,
        }

    legacy_snapshot = (
        absence_days,
        late_minutes,
        absence_amount,
        late_amount,
    )
    if any(value is not None for value in legacy_snapshot):
        if (
            late_occurrences is not None
            or any(value is None for value in legacy_snapshot)
            or absence_amount < 0
            or late_amount < 0
            or absence_amount + late_amount != payroll.deductions
            or not _attendance_history_is_unchanged(payroll)
        ):
            return None

        calculation = calculate_attendance_deductions(
            payroll.employee_id,
            payroll.pay_period_start,
            payroll.pay_period_end,
            payroll.basic_salary,
        )
        if (
            calculation["absence_days"] != absence_days
            or calculation["late_minutes"] != late_minutes
            or calculation["absence_deduction"] != absence_amount
            or calculation["late_deduction"] != late_amount
        ):
            return None
        return {
            "absence_days": absence_days,
            "absence_deduction": absence_amount,
            "late_minutes": late_minutes,
            "late_occurrences": calculation["late_occurrences"],
            "late_deduction": late_amount,
            "total_deductions": payroll.deductions,
        }

    if not _attendance_history_is_unchanged(payroll):
        return None

    calculation = calculate_attendance_deductions(
        payroll.employee_id,
        payroll.pay_period_start,
        payroll.pay_period_end,
        payroll.basic_salary,
    )
    if calculation["total_deductions"] != payroll.deductions:
        return None
    return {
        key: calculation[key]
        for key in (
            "absence_days",
            "absence_deduction",
            "late_minutes",
            "late_occurrences",
            "late_deduction",
            "total_deductions",
        )
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
