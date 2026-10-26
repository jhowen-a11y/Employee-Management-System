
from flask import abort, Blueprint, render_template, request, redirect, url_for, flash
from datetime import date, time
from flask_login import current_user
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import joinedload

from models import db
from models.attendance import Attendance
from models.employee import Employee
from models.user import User
from profile_storage import profile_picture_urls
from routes.employee_access import (
    current_employee,
    employee_scoped_query,
    management_required,
)

attendance_bp = Blueprint(
    "attendance",
    __name__,
    url_prefix="/attendance"
)


def parse_date(value):
    # Convert a form value to a date, returning None when it is invalid.
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def parse_time(value):
    # Convert a form value to a time, returning None when it is invalid.
    if not value:
        return None

    try:
        return time.fromisoformat(value)
    except (ValueError, TypeError):
        return None


# View all attendance records
@attendance_bp.route("/")
def attendance_list():
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    date_from_value = request.args.get("from", "").strip()
    date_to_value = request.args.get("to", "").strip()
    date_from = parse_date(date_from_value) if date_from_value else None
    date_to = parse_date(date_to_value) if date_to_value else None
    if (date_from_value and date_from is None) or (date_to_value and date_to is None):
        abort(400, description="Enter valid attendance date filters.")
    if date_from and date_to and date_to < date_from:
        abort(400, description="The end date cannot be earlier than the start date.")
    statuses = ("Present", "Absent", "Late", "On Leave")
    if status and status not in statuses:
        abort(400, description="Select a valid attendance status.")
    sort = request.args.get("sort", "employee").strip()
    direction = request.args.get("direction", "desc").strip().lower()
    sort_fields = {
        "employee": (Employee.last_name, Employee.first_name),
        "date": (Attendance.attendance_date,),
        "time_in": (Attendance.time_in,),
        "time_out": (Attendance.time_out,),
        "status": (Attendance.status,),
    }
    if sort not in sort_fields:
        sort = "employee"
    if direction not in {"asc", "desc"}:
        direction = "desc"
    sort_expressions = [
        expression.asc() if direction == "asc" else expression.desc()
        for expression in sort_fields[sort]
    ]

    query = employee_scoped_query(
        Attendance.query, Attendance.employee_id
    ).join(Attendance.employee)
    if search:
        search_pattern = f"%{search}%"
        search_filters = [
            Employee.first_name.ilike(search_pattern),
            Employee.last_name.ilike(search_pattern),
            (Employee.first_name + " " + Employee.last_name).ilike(search_pattern),
        ]
        if search.isdecimal():
            search_filters.append(
                cast(Employee.id, String).ilike(search_pattern)
            )
        query = query.filter(or_(*search_filters))
    if status:
        query = query.filter(Attendance.status == status)
    if date_from:
        query = query.filter(Attendance.attendance_date >= date_from)
    if date_to:
        query = query.filter(Attendance.attendance_date <= date_to)

    records = query.order_by(
        *sort_expressions, Attendance.id.desc()
    ).options(
        joinedload(Attendance.employee)
    ).paginate(
        page=request.args.get("page", 1, type=int),
        per_page=50,
        error_out=False,
    )
    picture_urls = profile_picture_urls(
        [
            record.employee.profile_picture
            for record in records.items
            if record.employee.profile_picture
        ]
    )

    return render_template(
        "attendance/list.html",
        records=records,
        profile_picture_urls=picture_urls,
        search=search,
        status=status,
        statuses=statuses,
        date_from=date_from_value,
        date_to=date_to_value,
        sort=sort,
        direction=direction,
    )


# View one attendance record
@attendance_bp.route("/<int:attendance_id>")
def attendance_detail(attendance_id):
    record_query = Attendance.query.filter_by(id=attendance_id)
    if current_user.role == User.EMPLOYEE:
        employee = current_employee()
        record_query = record_query.filter_by(
            employee_id=employee.id if employee else None
        )
    record = record_query.first_or_404()

    return render_template(
        "attendance/detail.html",
        record=record
    )


# Add an attendance record
@attendance_bp.route("/add", methods=["GET", "POST"])
@management_required
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
@management_required
def edit_attendance(attendance_id):
    record = db.get_or_404(Attendance, attendance_id)
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
@management_required
def delete_attendance(attendance_id):
    record = db.get_or_404(Attendance, attendance_id)

    db.session.delete(record)
    db.session.commit()

    flash("Attendance deleted successfully!", "success")
    return redirect(url_for("attendance.attendance_list"))
