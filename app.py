import hmac
import os
import secrets
from pathlib import Path

import click
from flask import Flask, abort, redirect, render_template, request, session, url_for
from dotenv import load_dotenv
from flask_login import LoginManager, current_user
from sqlalchemy.engine import URL
from werkzeug.security import generate_password_hash

from models import db
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

    required_settings = ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME")
    missing_settings = [
        name for name in required_settings if not os.getenv(name)
    ]
    if missing_settings:
        raise RuntimeError(
            "Missing required database settings: "
            + ", ".join(missing_settings)
        )

    try:
        database_port = int(os.getenv("DB_PORT", "5432"))
    except ValueError as error:
        raise RuntimeError("DB_PORT must be a valid port number.") from error
    if not 1 <= database_port <= 65535:
        raise RuntimeError("DB_PORT must be between 1 and 65535.")

    app.config.update(
        SECRET_KEY=secret_key,
        DEBUG=os.getenv("FLASK_DEBUG", "0").strip() == "1",
        SQLALCHEMY_DATABASE_URI=URL.create(
            drivername="postgresql+psycopg",
            username=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            host=os.environ["DB_HOST"],
            port=database_port,
            database=os.environ["DB_NAME"],
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
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
        if request.method == "POST" and request.endpoint in {
            "auth.logout",
            "users.add_user",
            "users.update_user_role",
            "employee.add_employee",
            "employee.edit_employee",
        }:
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
        return render_template("base.html")

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


if __name__ == "__main__":
    app = create_app()
    app.run(debug=app.config["DEBUG"])
