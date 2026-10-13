
from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import date

from models import db
from models.leave import Leave

leave_bp = Blueprint(
    "leave",
    __name__,
    url_prefix="/leaves"
)


# View all leave requests
@leave_bp.route("/")
def leave_list():
    leaves = Leave.query.order_by(
        Leave.created_at.desc()
    ).all()

    return render_template(
        "leave/list.html",
        leaves=leaves
    )


# Submit a leave request
@leave_bp.route("/add", methods=["GET", "POST"])
def add_leave():
    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        leave_type = request.form.get("leave_type", "").strip()
        start_date = request.form.get("start_date", "")
        end_date = request.form.get("end_date", "")
        reason = request.form.get("reason", "").strip()

        # Check required fields
        if not employee_id or not leave_type or not start_date or not end_date:
            flash("Please fill in all required fields.", "error")
            return redirect(url_for("leave.add_leave"))

        try:
            start_date = date.fromisoformat(start_date)
            end_date = date.fromisoformat(end_date)
        except ValueError:
            flash("Please enter valid dates.", "error")
            return redirect(url_for("leave.add_leave"))

        if end_date < start_date:
            flash("End date cannot be before the start date.", "error")
            return redirect(url_for("leave.add_leave"))

        leave = Leave(
            employee_id=employee_id,
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

    return render_template("leaves/add.html")


# View a specific leave request
@leave_bp.route("/<int:leave_id>")
def leave_detail(leave_id):
    leave = Leave.query.get_or_404(leave_id)

    return render_template(
        "leaves/detail.html",
        leave=leave
    )


# Update leave request status
@leave_bp.route("/<int:leave_id>/status", methods=["POST"])
def update_leave_status(leave_id):
    leave = Leave.query.get_or_404(leave_id)

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
def delete_leave(leave_id):
    leave = Leave.query.get_or_404(leave_id)

    db.session.delete(leave)
    db.session.commit()

    flash("Leave request deleted successfully!", "success")
    return redirect(url_for("leave.leave_list"))
