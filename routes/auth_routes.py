from datetime import date
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
from sqlalchemy import func, select
from werkzeug.security import check_password_hash

from models import db
from models.employee import Employee
from models.attendance import Attendance
from models.department import Department
from models.leave import Leave
from models.payroll import Payroll
from models.payslip_request import PayslipRequest
from models.travel_order import TravelOrder
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
    employee = current_user.employee
    attendance_records = (
        Attendance.query.filter_by(employee_id=employee.id)
        .order_by(Attendance.attendance_date.desc(), Attendance.id.desc())
        .limit(5)
        .all()
        if employee
        else []
    )
    leave_requests = (
        Leave.query.filter_by(employee_id=employee.id)
        .order_by(Leave.created_at.desc(), Leave.id.desc())
        .limit(5)
        .all()
        if employee
        else []
    )
    payroll_records = (
        Payroll.query.filter_by(employee_id=employee.id)
        .filter(Payroll.payment_date.is_not(None))
        .order_by(Payroll.pay_period_start.desc(), Payroll.id.desc())
        .limit(5)
        .all()
        if employee
        else []
    )
    payslip_requests = (
        PayslipRequest.query.filter_by(employee_id=employee.id)
        .order_by(PayslipRequest.request_date.desc(), PayslipRequest.id.desc())
        .limit(5)
        .all()
        if employee
        else []
    )
    travel_orders = (
        TravelOrder.query.filter_by(employee_id=employee.id)
        .order_by(TravelOrder.created_at.desc(), TravelOrder.id.desc())
        .limit(5)
        .all()
        if employee
        else []
    )
    return render_template(
        "employee/home.html",
        employee=employee,
        attendance_records=attendance_records,
        leave_requests=leave_requests,
        payroll_records=payroll_records,
        payslip_requests=payslip_requests,
        travel_orders=travel_orders,
    )


@auth_bp.route("/hr/home")
@login_required
def hr_home():
    # Show HR's daily people operations workload.
    if current_user.role != User.HR:
        abort(403)
    today = date.today()
    counts = db.session.execute(
        select(
            select(func.count(Employee.id))
            .scalar_subquery()
            .label("employee_count"),
            select(func.count(User.id))
            .scalar_subquery()
            .label("user_count"),
            select(func.count(Department.id))
            .scalar_subquery()
            .label("department_count"),
            select(func.count(func.distinct(Attendance.employee_id)))
            .where(
                Attendance.attendance_date == today,
                Attendance.status == "Present",
            )
            .scalar_subquery()
            .label("present_today_count"),
            select(func.count(func.distinct(Attendance.employee_id)))
            .where(
                Attendance.attendance_date == today,
                Attendance.status == "Absent",
            )
            .scalar_subquery()
            .label("absent_today_count"),
            select(func.count(Leave.id))
            .where(Leave.status == "Pending")
            .scalar_subquery()
            .label("pending_leave_count"),
            select(func.count(Payroll.id))
            .scalar_subquery()
            .label("payroll_count"),
            select(func.count(Payroll.id))
            .where(Payroll.payment_date.is_(None))
            .scalar_subquery()
            .label("pending_payroll_count"),
            select(func.count(PayslipRequest.id))
            .where(PayslipRequest.status == PayslipRequest.PENDING)
            .scalar_subquery()
            .label("pending_payslip_request_count"),
        )
    ).one()
    return render_template(
        "hr/home.html",
        employee_count=counts.employee_count,
        user_count=counts.user_count,
        department_count=counts.department_count,
        present_today_count=counts.present_today_count,
        absent_today_count=counts.absent_today_count,
        pending_leave_count=counts.pending_leave_count,
        payroll_count=counts.payroll_count,
        pending_payroll_count=counts.pending_payroll_count,
        pending_payslip_request_count=counts.pending_payslip_request_count,
        today=today,
    )


@auth_bp.route("/logout", methods=["POST"])
def logout():
    # Sign out the current user.
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))
