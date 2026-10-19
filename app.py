import hashlib
import hmac
import os
import secrets
from pathlib import Path


import click
from sqlalchemy import func, select
from flask import Flask, abort, redirect, render_template, request, session, url_for
from dotenv import load_dotenv
from flask_login import LoginManager, current_user
from werkzeug.security import generate_password_hash

from models import db, migrate
from models.attendance import Attendance
from models.department import Department
from models.employee import Employee
from models.leave import Leave
from models.payroll import Payroll
from models.user import User
from routes.auth_routes import auth_bp
from routes.employee_routes import employee_bp
from routes.attendance_routes import attendance_bp
from routes.department_routes import department_bp
from routes.leave_route import leave_bp
from routes.payroll_route import payroll_bp
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
        DEBUG=os.getenv("FLASK_DEBUG", "0").strip() == "1",
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SEND_FILE_MAX_AGE_DEFAULT=0,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SQLALCHEMY_DATABASE_URI"]:
        raise RuntimeError(
            "DATABASE_URL must be set in the environment or .env file."
        )

    static_assets = ("css/style.css", "js/script.js")
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
        return response

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "error"

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    @app.before_request
    def require_sign_in():
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

        return {"csrf_token": csrf_token}

    app.register_blueprint(auth_bp)
    app.register_blueprint(employee_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(department_bp)
    app.register_blueprint(leave_bp)
    app.register_blueprint(payroll_bp)
    app.register_blueprint(user_bp)

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
        return render_template(
            "admin/home.html",
            employee_count=counts.employee_count,
            department_count=counts.department_count,
            attendance_count=counts.attendance_count,
            pending_leave_count=counts.pending_leave_count,
            payroll_count=counts.payroll_count,
            user_count=counts.user_count,
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
