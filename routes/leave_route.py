
from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import date
from flask_login import current_user
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
    leaves = employee_scoped_query(
        Leave.query, Leave.employee_id
    ).order_by(
        Leave.created_at.desc(),
        Leave.id.desc(),
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
