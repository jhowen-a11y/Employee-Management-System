from flask import (
    current_app,
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from models import db
from routes.auth_routes import admin_required
from services.database_backups import (
    BackupError,
    backup_overview,
    create_backup,
    delete_backup,
    get_backup,
    restore_backup,
)


database_backup_bp = Blueprint("database_backup", __name__)


@database_backup_bp.route("/admin/database-backups")
@admin_required
def index():
    overview = backup_overview()
    overview["database_name"] = "Unavailable"
    try:
        if db.engine.dialect.name == "postgresql":
            with db.engine.connect() as connection:
                overview["database_name"] = connection.scalar(
                    text("SELECT current_database()")
                )
                overview["connection_status"] = "Connected"
    except SQLAlchemyError as error:
        current_app.logger.error(
            "Could not read database backup overview: error_type=%s",
            type(error).__name__,
        )
    return render_template("admin/database_backup.html", overview=overview)


@database_backup_bp.route("/admin/database-backups/create", methods=["POST"])
@admin_required
def create():
    encrypted = request.form.get("encrypt") == "on"
    password = request.form.get("encryption_password", "")
    if encrypted and len(password) < 12:
        flash("Use an encryption password with at least 12 characters.", "error")
        return redirect(url_for("database_backup.index"))

    try:
        create_backup(current_user.username, password if encrypted else None)
    except BackupError as error:
        flash(error.public_message, "error")
    else:
        flash("Backup created successfully.", "success")
    return redirect(url_for("database_backup.index"))


@database_backup_bp.route(
    "/admin/database-backups/<backup_id>/download"
)
@admin_required
def download(backup_id):
    backup = get_backup(backup_id)
    if backup is None:
        abort(404)
    response = send_file(
        backup["path"],
        as_attachment=True,
        download_name=backup["filename"],
        mimetype="application/zip",
        conditional=False,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@database_backup_bp.route(
    "/admin/database-backups/<backup_id>/delete",
    methods=["POST"],
)
@admin_required
def delete(backup_id):
    if not delete_backup(backup_id):
        abort(404)
    flash("Backup deleted.", "success")
    return redirect(url_for("database_backup.index"))


@database_backup_bp.route("/admin/database-backups/restore", methods=["POST"])
@admin_required
def restore():
    if (
        request.form.get("confirm_overwrite") != "on"
        or request.form.get("confirmed_restore") != "yes"
    ):
        flash("Confirm the restore in the confirmation dialog to continue.", "error")
        return redirect(url_for("database_backup.index"))

    upload = request.files.get("backup_file")
    if upload is None or not upload.filename:
        flash("Choose a backup package to restore.", "error")
        return redirect(url_for("database_backup.index"))

    try:
        restore_backup(
            upload.stream,
            request.form.get("restore_database_name", ""),
            request.form.get("restore_password", ""),
        )
    except BackupError as error:
        flash(error.public_message, "error")
    else:
        flash(
            "Backup restored into the new database. Your active database was not changed.",
            "success",
        )
    return redirect(url_for("database_backup.index"))
