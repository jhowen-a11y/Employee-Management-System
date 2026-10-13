import os
from pathlib import Path

from flask import Flask, render_template
from dotenv import load_dotenv
from sqlalchemy.engine import URL

from models import db
from routes.employee_routes import employee_bp
from routes.attendance_routes import attendance_bp
from routes.department_routes import department_bp
from routes.leave_route import leave_bp
from routes.payroll_route import payroll_bp

def create_app():
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
        database_port = int(os.getenv("DB_PORT", "3306"))
    except ValueError as error:
        raise RuntimeError("DB_PORT must be a valid port number.") from error
    if not 1 <= database_port <= 65535:
        raise RuntimeError("DB_PORT must be between 1 and 65535.")

    app.config.update(
        SECRET_KEY=secret_key,
        DEBUG=os.getenv("FLASK_DEBUG", "0").strip() == "1",
        SQLALCHEMY_DATABASE_URI=URL.create(
            drivername="mysql+pymysql",
            username=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            host=os.environ["DB_HOST"],
            port=database_port,
            database=os.environ["DB_NAME"],
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    db.init_app(app)
    app.register_blueprint(employee_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(department_bp)
    app.register_blueprint(leave_bp)
    app.register_blueprint(payroll_bp)

    @app.route("/")
    def index():
        return render_template("base.html")

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=app.config["DEBUG"])
