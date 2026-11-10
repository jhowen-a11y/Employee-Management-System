import hashlib
import hmac
import math
import os
import secrets
import time
from pathlib import Path


import click
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException
from sqlalchemy.orm import joinedload
from flask import (
    Flask,
    abort,
    g,
    has_request_context,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from dotenv import load_dotenv
from flask_login import LoginManager, current_user
from markupsafe import escape
from werkzeug.security import generate_password_hash

from models import db, migrate
from models.attendance import Attendance
from models.department import Department
from models.employee import Employee
from models.leave import Leave
from models.payroll import Payroll
from models.payslip_request import PayslipRequest
from models.travel_order import TravelOrder
from models.user import User
from profile_storage import profile_picture_url
from routes.auth_routes import auth_bp
from routes.database_backup_routes import database_backup_bp
from routes.employee_routes import employee_bp
from routes.attendance_routes import attendance_bp
from routes.department_routes import department_bp
from routes.leave_route import leave_bp
from routes.payroll_route import payroll_bp
from routes.payslip_routes import payslip_bp
from routes.travel_order_routes import travel_order_bp
from routes.user_routes import user_bp

login_manager = LoginManager()

def create_app(test_config=None):
    load_dotenv(Path(__file__).resolve().with_name(".env"))

    app = Flask(__name__)

    secret_key = os.getenv("SECRET_KEY")
    if not secret_key:
        raise RuntimeError("SECRET_KEY must be set in the environment or .env file.")

    app.config.update(
        SECRET_KEY=secret_key,
        DEBUG=False,
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SEND_FILE_MAX_AGE_DEFAULT=31536000,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        BACKUP_UPLOAD_MAX_CONTENT_LENGTH=513 * 1024 * 1024,
        PAYROLL_MONTHLY_WORKING_DAYS=os.getenv(
            "EMS_PAYROLL_MONTHLY_WORKING_DAYS", "22"
        ),
        PAYROLL_HOURS_PER_DAY=os.getenv("EMS_PAYROLL_HOURS_PER_DAY", "8"),
        PAYROLL_SHIFT_START=os.getenv("EMS_PAYROLL_SHIFT_START", "08:00"),
        PAYROLL_LATE_GRACE_MINUTES=os.getenv(
            "EMS_PAYROLL_LATE_GRACE_MINUTES", "0"
        ),
        PAYROLL_NON_WORKING_DATES=os.getenv(
            "EMS_PAYROLL_NON_WORKING_DATES", ""
        ),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SQLALCHEMY_DATABASE_URI"]:
        raise RuntimeError(
            "DATABASE_URL must be set in the environment or .env file."
        )

    static_assets = (
        "css/style.css",
        "js/script.js",
        "js/database_backup.js",
        "js/payroll_deductions.js",
    )
    static_asset_versions = {
        filename: hashlib.sha256(
            (Path(app.static_folder) / filename).read_bytes()
        ).hexdigest()
        for filename in static_assets
    }

    @app.context_processor
    def static_asset_context():
        return {"static_asset_version": static_asset_versions.__getitem__}

    @app.after_request
    def cache_versioned_static_assets(response):
        if request.endpoint == "static" and response.status_code == 200:
            filename = (request.view_args or {}).get("filename")
            expected_version = static_asset_versions.get(filename)
            if (
                expected_version
                and request.args.get("v") == expected_version
            ):
                response.cache_control.no_cache = None
                response.cache_control.public = True
                response.cache_control.max_age = 31536000
                response.cache_control.immutable = True
        if hasattr(g, "request_started_at"):
            app_duration = (time.perf_counter() - g.request_started_at) * 1000
            database_duration = getattr(g, "database_duration_ms", 0.0)
            database_query_count = getattr(g, "database_query_count", 0)
            signing_duration = getattr(g, "profile_picture_signing_ms", 0.0)
            response.headers["Server-Timing"] = (
                f"app;dur={app_duration:.1f}, "
                f"database;dur={database_duration:.1f};"
                f'desc="{database_query_count} queries", '
                f"profile-storage;dur={signing_duration:.1f}"
            )
        return response

    db.init_app(app)
    migrate.init_app(app, db)

    def render_safe_error(code, title, message):
        accepts_json = (
            request.accept_mimetypes["application/json"]
            > request.accept_mimetypes["text/html"]
        )
        is_api_endpoint = (
            request.path.startswith("/api/")
            or request.path.endswith("/api")
        )
        if accepts_json or is_api_endpoint:
            return jsonify({"error": message}), code
        page = f"""\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{code} — {escape(title)}</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: #f3f6fb;
      color: #1f2937;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .card {{
      width: min(90vw, 560px);
      background: #fff;
      border-radius: 18px;
      box-shadow: 0 18px 40px rgba(15, 23, 42, 0.12);
      padding: 2rem 2rem 1.5rem;
      text-align: center;
    }}
    h1 {{ margin: 0 0 0.75rem; font-size: clamp(2rem, 3vw, 2.5rem); }}
    p {{ margin: 0 0 1rem; color: #4b5563; }}
    .actions {{ display: flex; justify-content: center; gap: 0.8rem; flex-wrap: wrap; }}
    .button {{
      display: inline-block;
      background: #5a64f4;
      color: #fff;
      text-decoration: none;
      border: none;
      border-radius: 10px;
      padding: 0.8rem 1.3rem;
      cursor: pointer;
      font-weight: 600;
    }}
    .button.secondary {{
      background: #e5e7eb;
      color: #111827;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{escape(title)}</h1>
    <p>{escape(message)}</p>
    <div class="actions">
      <button class="button" type="button" onclick="window.location.reload()">Retry</button>
      <a class="button secondary" href="{escape(url_for('index'))}">Return home</a>
    </div>
  </div>
</body>
</html>
"""
        return page, code

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        code = error.code or 500
        title_map = {
            400: "Bad request",
            401: "Please sign in",
            403: "Access denied",
            404: "Page not found",
            405: "Method not allowed",
            429: "Too many requests",
            413: "Upload too large",
            500: "Service unavailable",
        }
        title = title_map.get(code, "Request unavailable")
        message = error.description or "Please try again later."
        if code == 413:
            message = "The uploaded file exceeds the 512 MB size limit."
        if code == 500:
            message = "The service is temporarily unavailable. Please try again."
        return render_safe_error(code, title, message)

    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(error):
        original_error = getattr(error, "orig", None)
        app.logger.error(
            "Database request failed: endpoint=%s path=%s error_type=%s "
            "driver_error_type=%s",
            request.endpoint,
            request.path,
            type(error).__name__,
            type(original_error).__name__ if original_error else "unknown",
        )
        return render_safe_error(
            503,
            "Service unavailable",
            "The database is temporarily unavailable. Please try again.",
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            return handle_http_exception(error)
        app.logger.error(
            "Unhandled request failure: endpoint=%s path=%s error_type=%s",
            request.endpoint,
            request.path,
            type(error).__name__,
        )
        return render_safe_error(
            500,
            "Service unavailable",
            "The service is temporarily unavailable. Please try again.",
        )

    @app.before_request
    def start_request_timing():
        g.request_started_at = time.perf_counter()
        g.database_duration_ms = 0.0
        g.database_query_count = 0
        g.profile_picture_signing_ms = 0.0

    def start_database_query(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        if context is None:
            return
        context._ems_query_started_at = time.perf_counter()

    def finish_database_query(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        query_started_at = getattr(context, "_ems_query_started_at", None)
        if query_started_at is None or not has_request_context():
            return
        g.database_query_count += 1
        g.database_duration_ms += (
            time.perf_counter() - query_started_at
        ) * 1000

    with app.app_context():
        event.listen(db.engine, "before_cursor_execute", start_database_query)
        event.listen(db.engine, "after_cursor_execute", finish_database_query)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "error"

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.execute(
                select(User)
                .options(joinedload(User.employee))
                .where(User.id == int(user_id))
            ).scalar_one_or_none()
        except (TypeError, ValueError):
            return None

    @app.before_request
    def require_sign_in():
        if request.endpoint == "database_backup.restore":
            request.max_content_length = app.config[
                "BACKUP_UPLOAD_MAX_CONTENT_LENGTH"
            ]
        if request.endpoint == "auth.login":
            if request.method == "POST":
                return validate_csrf_token()
            return None
        if request.endpoint == "static":
            return None
        if request.endpoint and not current_user.is_authenticated:
            return login_manager.unauthorized()
        if request.method == "POST":
            return validate_csrf_token()
        return None

    def validate_csrf_token():
        expected_token = session.get("_csrf_token")
        submitted_token = request.form.get("_csrf_token", "")
        if not expected_token or not hmac.compare_digest(
            expected_token, submitted_token
        ):
            abort(400, description="The form has expired. Please try again.")
        return None

    @app.context_processor
    def csrf_token_context():
        def csrf_token():
            token = session.get("_csrf_token")
            if token is None:
                token = secrets.token_urlsafe(32)
                session["_csrf_token"] = token
            return token

        return {
            "csrf_token": csrf_token,
            "profile_picture_url": profile_picture_url,
        }

    app.register_blueprint(auth_bp)
    app.register_blueprint(employee_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(department_bp)
    app.register_blueprint(leave_bp)
    app.register_blueprint(payroll_bp)
    app.register_blueprint(payslip_bp)
    app.register_blueprint(travel_order_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(database_backup_bp)

    @app.route("/")
    def index():
        if current_user.role == User.EMPLOYEE:
            return redirect(url_for("auth.employee_home"))
        if current_user.role == User.HR:
            return redirect(url_for("auth.hr_home"))
        counts = db.session.execute(
            select(
                select(func.count(Employee.id))
                .scalar_subquery()
                .label("employee_count"),
                select(func.count(Department.id))
                .scalar_subquery()
                .label("department_count"),
                select(func.count(Attendance.id))
                .scalar_subquery()
                .label("attendance_count"),
                select(func.count(Leave.id))
                .where(Leave.status == "Pending")
                .scalar_subquery()
                .label("pending_leave_count"),
                select(func.count(Payroll.id))
                .scalar_subquery()
                .label("payroll_count"),
                select(func.count(User.id))
                .scalar_subquery()
                .label("user_count"),
            )
        ).one()
        role_counts = dict(
            db.session.execute(
                select(User.role, func.count(User.id))
                .group_by(User.role)
            ).all()
        )
        role_distribution = []
        chart_offset = 0.0
        chart_circumference = 2 * math.pi * 40
        role_labels = {
            User.EMPLOYEE: "Employee",
            User.HR: "HR",
            User.ADMIN: "Admin",
        }

        def point_on_circle(radius, angle):
            angle_radians = math.radians(angle)
            return (
                50 + radius * math.cos(angle_radians),
                50 + radius * math.sin(angle_radians),
            )

        for role in (User.EMPLOYEE, User.HR, User.ADMIN):
            role_count = role_counts.get(role, 0)
            percentage = (
                role_count * 100 / counts.user_count
                if counts.user_count
                else 0
            )
            arc_length = (
                chart_circumference * role_count / counts.user_count
                if counts.user_count
                else 0
            )
            start_angle = -90 + chart_offset / chart_circumference * 360
            end_angle = start_angle + percentage * 3.6

            segment_path = ""
            if role_count == counts.user_count and counts.user_count:
                segment_path = (
                    "M 50 10 A 40 40 0 1 1 50 90 A 40 40 0 1 1 50 10 "
                    "L 50 23 A 27 27 0 1 0 50 77 A 27 27 0 1 0 50 23 Z"
                )
            elif role_count:
                outer_start = point_on_circle(40, start_angle)
                outer_end = point_on_circle(40, end_angle)
                inner_end = point_on_circle(27, end_angle)
                inner_start = point_on_circle(27, start_angle)
                large_arc = 1 if percentage > 50 else 0
                segment_path = (
                    f"M {outer_start[0]:.3f} {outer_start[1]:.3f} "
                    f"A 40 40 0 {large_arc} 1 {outer_end[0]:.3f} {outer_end[1]:.3f} "
                    f"L {inner_end[0]:.3f} {inner_end[1]:.3f} "
                    f"A 27 27 0 {large_arc} 0 {inner_start[0]:.3f} {inner_start[1]:.3f} Z"
                )
            role_distribution.append(
                {
                    "role": role,
                    "label": role_labels[role],
                    "count": role_count,
                    "percentage": percentage,
                    "path": segment_path,
                }
            )
            chart_offset += arc_length
        return render_template(
            "admin/home.html",
            employee_count=counts.employee_count,
            department_count=counts.department_count,
            attendance_count=counts.attendance_count,
            pending_leave_count=counts.pending_leave_count,
            payroll_count=counts.payroll_count,
            user_count=counts.user_count,
            role_distribution=role_distribution,
        )

    @app.cli.command("create-admin")
    def create_admin():
        """Create the first administrator account without public sign-up."""
        if User.query.filter_by(role=User.ADMIN).first():
            raise click.ClickException(
                "An administrator already exists. Create additional users "
                "from the signed-in admin screen."
            )

        username = click.prompt("Admin username").strip()
        email = click.prompt("Admin email").strip()
        password = click.prompt(
            "Admin password", hide_input=True, confirmation_prompt=True
        )

        if not username or len(username) > 50:
            raise click.ClickException("Username must be 1 to 50 characters.")
        if not email or len(email) > 120:
            raise click.ClickException("Email must be 1 to 120 characters.")
        if len(password) < 8:
            raise click.ClickException(
                "Password must be at least 8 characters."
            )
        if User.query.filter_by(username=username).first():
            raise click.ClickException("That username is already in use.")
        if User.query.filter_by(email=email).first():
            raise click.ClickException("That email address is already in use.")

        admin = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            role=User.ADMIN,
        )
        db.session.add(admin)
        db.session.commit()
        click.echo("Administrator account created.")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"])
