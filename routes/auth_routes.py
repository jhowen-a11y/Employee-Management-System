from functools import wraps

import secrets
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash

from models.employee import Employee
from models.attendance import Attendance
from models.department import Department
from models.leave import Leave
from models.payroll import Payroll
from models.user import User


auth_bp = Blueprint("auth", __name__)


def admin_required(view):
    # Restrict a view to signed-in administrators.
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        # Reject non-admin users before running the protected view.
        if current_user.role != User.ADMIN:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def landing_url_for(user):
    # Choose the home page appropriate for the user's role.
    if user.role == User.EMPLOYEE:
        return url_for("auth.employee_home")
    if user.role == User.HR:
        return url_for("auth.hr_home")
    return url_for("index")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # Authenticate a user and redirect them to a safe destination.
    if current_user.is_authenticated:
        return redirect(landing_url_for(current_user))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user is None or not check_password_hash(user.password_hash, password):
            flash("Invalid username or password.", "error")
        else:
            next_url = request.args.get("next")
            session.clear()
            login_user(user)
            session["_csrf_token"] = secrets.token_urlsafe(32)
            parsed_next_url = urlsplit(next_url or "")
            if (
                next_url
                and parsed_next_url.scheme == ""
                and parsed_next_url.netloc == ""
                and next_url.startswith("/")
                and not next_url.startswith("//")
                and "\\" not in next_url
            ):
                return redirect(next_url)
            return redirect(landing_url_for(user))

    return render_template("auth/login.html")


@auth_bp.route("/employee/home")
@login_required
def employee_home():
    # Show the signed-in employee's attendance, leave, and payroll records.
    if current_user.role != User.EMPLOYEE:
        abort(403)
    employee = Employee.query.filter_by(user_id=current_user.id).first()
    attendance_records = sorted(
        employee.attendance_records,
        key=lambda record: record.attendance_date,
        reverse=True,
    ) if employee else []
    leave_requests = sorted(
        employee.leave_requests,
        key=lambda leave: leave.created_at,
        reverse=True,
    ) if employee else []
    payroll_records = sorted(
        employee.payroll_records,
        key=lambda payroll: payroll.pay_period_start,
        reverse=True,
    ) if employee else []
    return render_template(
        "employee/home.html",
        employee=employee,
        attendance_records=attendance_records,
        leave_requests=leave_requests,
        payroll_records=payroll_records,
    )


@auth_bp.route("/hr/home")
@login_required
def hr_home():
    # Show HR dashboard counts for the organization's records.
    if current_user.role != User.HR:
        abort(403)
    return render_template(
        "hr/home.html",
        employee_count=Employee.query.count(),
        user_count=User.query.count(),
        department_count=Department.query.count(),
        attendance_count=Attendance.query.count(),
        pending_leave_count=Leave.query.filter_by(status="Pending").count(),
        payroll_count=Payroll.query.count(),
    )


@auth_bp.route("/logout", methods=["POST"])
def logout():
    # Sign out the current user.
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))
