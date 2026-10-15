from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from sqlalchemy import func
from werkzeug.security import generate_password_hash

from models import db
from models.user import User

user_bp = Blueprint("users", __name__, url_prefix="/users")


@user_bp.before_request
def require_admin():
    if current_user.role != User.ADMIN:
        abort(403)


@user_bp.route("/")
def user_list():
    users = User.query.order_by(User.username.asc()).all()
    return render_template("users/list.html", users=users, roles=User.ROLES)


@user_bp.route("/add", methods=["GET", "POST"])
def add_user():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "").strip()

        if not username or not email or not password:
            flash("Complete all required fields.", "error")
        elif len(username) > 50 or len(email) > 120:
            flash("Username or email is too long.", "error")
        elif len(password) < 8:
            flash("The account password must be at least 8 characters.", "error")
        elif role not in User.ROLES:
            flash("Select a valid role.", "error")
        elif User.query.filter_by(username=username).first():
            flash("That username is already in use.", "error")
        elif User.query.filter_by(email=email).first():
            flash("That email address is already in use.", "error")
        else:
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                role=role,
            )
            db.session.add(user)
            db.session.commit()
            flash("User added successfully.", "success")
            return redirect(url_for("users.user_list"))

    return render_template("users/add.html", roles=User.ROLES)


@user_bp.route("/<int:user_id>/role", methods=["POST"])
def update_user_role(user_id):
    user = db.get_or_404(User, user_id)
    role = request.form.get("role", "").strip()

    if role not in User.ROLES:
        flash("Select a valid role.", "error")
    elif user.id == current_user.id:
        flash("You cannot change your own role.", "error")
    elif user.role == User.ADMIN and role != User.ADMIN:
        admin_count = db.session.query(func.count(User.id)).filter_by(
            role=User.ADMIN
        ).scalar()
        if admin_count <= 1:
            flash("The last administrator cannot be demoted.", "error")
        else:
            user.role = role
            db.session.commit()
            flash("User role updated successfully.", "success")
    else:
        user.role = role
        db.session.commit()
        flash("User role updated successfully.", "success")

    return redirect(url_for("users.user_list"))


@user_bp.route("/api")
def get_all_users():
    users = User.query.order_by(User.username.asc()).all()
    return jsonify(
        users=[
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
            }
            for user in users
        ]
    )
