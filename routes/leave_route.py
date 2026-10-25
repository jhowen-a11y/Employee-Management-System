
from flask import abort, Blueprint, render_template, request, redirect, url_for, flash
from datetime import date
from flask_login import current_user
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import joinedload

from models import db
from models.employee import Employee
from models.leave import Leave
from models.user import User
from profile_storage import profile_picture_urls
from routes.employee_access import (
    current_employee,
    employee_scoped_query,
    management_required,
)

leave_bp = Blueprint(
    "leave",
    __name__,
    url_prefix="/leaves"
)


# View all leave requests
@leave_bp.route("/")
def leave_list():
    search = request.args.get("q", "").strip()
    leave_type = request.args.get("leave_type", "").strip()
    status = request.args.get("status", "").strip()
    date_from_value = request.args.get("from", "").strip()
    date_to_value = request.args.get("to", "").strip()
    try:
        date_from = date.fromisoformat(date_from_value) if date_from_value else None
        date_to = date.fromisoformat(date_to_value) if date_to_value else None
    except ValueError:
        abort(400, description="Enter valid leave date filters.")
    if (date_from_value and date_from is None) or (date_to_value and date_to is None):
        abort(400, description="Enter valid leave date filters.")
    leave_types = ("Annual", "Sick", "Personal", "Maternity", "Paternity", "Other")
    statuses = ("Pending", "Approved", "Rejected")
    if leave_type and leave_type not in leave_types:
        abort(400, description="Select a valid leave type.")
    if status and status not in statuses:
        abort(400, description="Select a valid leave status.")
    sort = request.args.get("sort", "submission_date").strip()
    direction = request.args.get("direction", "desc").strip().lower()
    sort_fields = {
        "employee": (Employee.last_name, Employee.first_name),
        "leave_type": (Leave.leave_type,),
        "start_date": (Leave.start_date,),
        "end_date": (Leave.end_date,),
        "submission_date": (Leave.created_at,),
        "status": (Leave.status,),
    }
    if sort not in sort_fields:
        sort = "submission_date"
    if direction not in {"asc", "desc"}:
        direction = "desc"
    sort_expressions = [
        expression.asc() if direction == "asc" else expression.desc()
        for expression in sort_fields[sort]
    ]

    query = employee_scoped_query(
        Leave.query, Leave.employee_id
    ).join(Leave.employee)
    if search:
        search_pattern = f"%{search}%"
        search_filters = [
            Employee.first_name.ilike(search_pattern),
            Employee.last_name.ilike(search_pattern),
            (Employee.first_name + " " + Employee.last_name).ilike(search_pattern),
        ]
        if search.isdecimal():
            search_filters.append(cast(Employee.id, String).ilike(search_pattern))
        query = query.filter(or_(*search_filters))
    if leave_type:
        query = query.filter(Leave.leave_type == leave_type)
    if status:
        query = query.filter(Leave.status == status)
    if date_from:
        query = query.filter(Leave.end_date >= date_from)
    if date_to:
        query = query.filter(Leave.start_date <= date_to)

    leaves = query.order_by(
        *sort_expressions, Leave.id.desc()
    ).options(
        joinedload(Leave.employee)
    ).paginate(
        page=request.args.get("page", 1, type=int),
        per_page=50,
        error_out=False,
    )
    picture_urls = profile_picture_urls(
        [
            leave.employee.profile_picture
            for leave in leaves.items
            if leave.employee.profile_picture
        ]
    )

    return render_template(
        "leave/list.html",
        leaves=leaves,
        profile_picture_urls=picture_urls,
        search=search,
        leave_type=leave_type,
        status=status,
        leave_types=leave_types,
        statuses=statuses,
        date_from=date_from_value,
        date_to=date_to_value,
        sort=sort,
        direction=direction,
    )


# Submit a leave request
@leave_bp.route("/add", methods=["GET", "POST"])
def add_leave():
    is_employee = current_user.role == User.EMPLOYEE
    employee = current_employee() if is_employee else None
    employees = (
        [employee] if employee else []
    ) if is_employee else Employee.query.order_by(
            Employee.last_name.asc(),
            Employee.first_name.asc()
        ).all()

    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        if is_employee:
            employee_id = employee.id if employee else None
        leave_type = request.form.get("leave_type", "").strip()
        start_date = request.form.get("start_date", "")
        end_date = request.form.get("end_date", "")
        reason = request.form.get("reason", "").strip()

        allowed_leave_types = (
            "Annual", "Sick", "Personal", "Maternity", "Paternity", "Other"
        )
        selected_employee = (
            db.session.get(Employee, employee_id) if employee_id else None
        )

        if (
            selected_employee is None
            or not leave_type
            or not start_date
            or not end_date
        ):
            flash("Please fill in all required fields.", "error")
        elif leave_type not in allowed_leave_types:
            flash("Select a valid leave type.", "error")
        else:
            try:
                start_date = date.fromisoformat(start_date)
                end_date = date.fromisoformat(end_date)
            except ValueError:
                flash("Please enter valid dates.", "error")
            else:
                if end_date < start_date:
                    flash("End date cannot be before the start date.", "error")
                else:
                    leave = Leave(
                        employee_id=selected_employee.id,
                        leave_type=leave_type,
                        start_date=start_date,
                        end_date=end_date,
                        reason=reason or None,
                        status="Pending"
                    )

                    db.session.add(leave)
                    db.session.commit()

                    flash("Leave request submitted successfully!", "success")
                    return redirect(url_for("leave.leave_list"))

        return render_template(
            "leave/add.html",
            employees=employees,
            allowed_leave_types=allowed_leave_types,
        )

    return render_template(
        "leave/add.html",
        employees=employees,
        allowed_leave_types=(
            "Annual", "Sick", "Personal", "Maternity", "Paternity", "Other"
        ),
    )


# View a specific leave request
@leave_bp.route("/<int:leave_id>")
def leave_detail(leave_id):
    leave_query = Leave.query.filter_by(id=leave_id)
    if current_user.role == User.EMPLOYEE:
        employee = current_employee()
        leave_query = leave_query.filter_by(
            employee_id=employee.id if employee else None
        )
    leave = leave_query.first_or_404()

    return render_template(
        "leave/detail.html",
        leave=leave
    )


# Update leave request status
@leave_bp.route("/<int:leave_id>/status", methods=["POST"])
@management_required
def update_leave_status(leave_id):
    leave = db.get_or_404(Leave, leave_id)

    new_status = request.form.get("status", "").strip()

    allowed_statuses = {"Pending", "Approved", "Rejected"}

    if new_status not in allowed_statuses:
        flash("Invalid leave status.", "error")
        return redirect(url_for("leave.leave_detail", leave_id=leave.id))

    leave.status = new_status
    db.session.commit()

    flash("Leave status updated successfully!", "success")
    return redirect(url_for("leave.leave_detail", leave_id=leave.id))


# Delete a leave request
@leave_bp.route("/<int:leave_id>/delete", methods=["POST"])
@management_required
def delete_leave(leave_id):
    leave = db.get_or_404(Leave, leave_id)

    db.session.delete(leave)
    db.session.commit()

    flash("Leave request deleted successfully!", "success")
    return redirect(url_for("leave.leave_list"))
