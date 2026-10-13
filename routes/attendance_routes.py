
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from datetime import date, time

from models import db
from models.attendance import Attendance
from models.employee import Employee

attendance_bp = Blueprint(
    "attendance",
    __name__,
    url_prefix="/attendance"
)


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def parse_time(value):
    if not value:
        return None

    try:
        return time.fromisoformat(value)
    except (ValueError, TypeError):
        return None


# View all attendance records
@attendance_bp.route("/")
@login_required
def attendance_list():
    records = Attendance.query.order_by(
        Attendance.attendance_date.desc()
    ).all()

    return render_template(
        "attendance/list.html",
        records=records
    )


# View one attendance record
@attendance_bp.route("/<int:attendance_id>")
@login_required
def attendance_detail(attendance_id):
    record = Attendance.query.get_or_404(attendance_id)

    return render_template(
        "attendance/detail.html",
        record=record
    )


# Add an attendance record
@attendance_bp.route("/add", methods=["GET", "POST"])
@login_required
def add_attendance():
    employees = Employee.query.order_by(Employee.last_name).all()

    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        attendance_date = parse_date(
            request.form.get("attendance_date", "")
        )
        time_in_value = request.form.get("time_in", "")
        time_out_value = request.form.get("time_out", "")
        status = request.form.get("status", "Present").strip()

        allowed_statuses = {
            "Present", "Absent", "Late", "On Leave"
        }

        employee = (
            db.session.get(Employee, employee_id)
            if employee_id else None
        )

        time_in = parse_time(time_in_value)
        time_out = parse_time(time_out_value)

        if employee is None:
            flash("Please select a valid employee.", "error")
        elif attendance_date is None:
            flash("Please enter a valid attendance date.", "error")
        elif status not in allowed_statuses:
            flash("Invalid attendance status.", "error")
        elif time_in_value and time_in is None:
            flash("Please enter a valid time-in.", "error")
        elif time_out_value and time_out is None:
            flash("Please enter a valid time-out.", "error")
        elif time_in and time_out and time_out < time_in:
            flash("Time-out cannot be earlier than time-in.", "error")
        else:
            record = Attendance(
                employee_id=employee.id,
                attendance_date=attendance_date,
                time_in=time_in,
                time_out=time_out,
                status=status
            )

            db.session.add(record)
            db.session.commit()

            flash("Attendance added successfully!", "success")
            return redirect(url_for("attendance.attendance_list"))

        return render_template(
            "attendance/add.html",
            employees=employees
        )

    return render_template(
        "attendance/add.html",
        employees=employees
    )


# Edit an attendance record
@attendance_bp.route(
    "/<int:attendance_id>/edit",
    methods=["GET", "POST"]
)
@login_required
def edit_attendance(attendance_id):
    record = Attendance.query.get_or_404(attendance_id)
    employees = Employee.query.order_by(Employee.last_name).all()

    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        attendance_date = parse_date(
            request.form.get("attendance_date", "")
        )
        time_in_value = request.form.get("time_in", "")
        time_out_value = request.form.get("time_out", "")
        status = request.form.get("status", "Present").strip()

        allowed_statuses = {
            "Present", "Absent", "Late", "On Leave"
        }

        employee = (
            db.session.get(Employee, employee_id)
            if employee_id else None
        )

        time_in = parse_time(time_in_value)
        time_out = parse_time(time_out_value)

        if employee is None:
            flash("Please select a valid employee.", "error")
        elif attendance_date is None:
            flash("Please enter a valid attendance date.", "error")
        elif status not in allowed_statuses:
            flash("Invalid attendance status.", "error")
        elif time_in_value and time_in is None:
            flash("Please enter a valid time-in.", "error")
        elif time_out_value and time_out is None:
            flash("Please enter a valid time-out.", "error")
        elif time_in and time_out and time_out < time_in:
            flash("Time-out cannot be earlier than time-in.", "error")
        else:
            record.employee_id = employee.id
            record.attendance_date = attendance_date
            record.time_in = time_in
            record.time_out = time_out
            record.status = status

            db.session.commit()

            flash("Attendance updated successfully!", "success")
            return redirect(url_for("attendance.attendance_list"))

        return render_template(
            "attendance/edit.html",
            record=record,
            employees=employees
        )

    return render_template(
        "attendance/edit.html",
        record=record,
        employees=employees
    )


# Delete an attendance record
@attendance_bp.route(
    "/<int:attendance_id>/delete",
    methods=["POST"]
)
@login_required
def delete_attendance(attendance_id):
    record = Attendance.query.get_or_404(attendance_id)

    db.session.delete(record)
    db.session.commit()

    flash("Attendance deleted successfully!", "success")
    return redirect(url_for("attendance.attendance_list"))
