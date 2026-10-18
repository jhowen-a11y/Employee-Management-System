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
from sqlalchemy.orm import selectinload
from werkzeug.security import check_password_hash, generate_password_hash

from models import db
from models.employee import Employee
from models.user import User

user_bp = Blueprint("users", __name__, url_prefix="/users")
ACCOUNT_CREATION_ROLES = (User.ADMIN, User.HR)


@user_bp.before_request
def require_admin():
    # Allow only administrators, except when users edit their own profile.
    if (
        current_user.role != User.ADMIN
        and request.endpoint != "users.edit_profile"
    ):
        abort(403)


@user_bp.route("/")
def user_list():
    # Show all user accounts.
    users = User.query.options(
        selectinload(User.employee)
    ).order_by(User.username.asc()).paginate(
        page=request.args.get("page", 1, type=int),
        per_page=50,
        error_out=False,
    )
    return render_template("users/list.html", users=users, roles=User.ROLES)


@user_bp.route("/profile", methods=["GET", "POST"])
def edit_profile():
    # Update the signed-in user's profile and optionally their password.
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        duplicate_username = User.query.filter(
            User.username == username,
            User.id != current_user.id,
        ).first()
        duplicate_email = User.query.filter(
            User.email == email,
            User.id != current_user.id,
        ).first()

        if not username or not email:
            flash("Username and email are required.", "error")
        elif len(username) > 50 or len(email) > 120:
            flash("Username or email is too long.", "error")
        elif duplicate_username:
            flash("That username is already in use.", "error")
        elif duplicate_email:
            flash("That email address is already in use.", "error")
        elif new_password and not check_password_hash(
            current_user.password_hash, current_password
        ):
            flash("Enter your current password to change it.", "error")
        elif new_password and len(new_password) < 8:
            flash("The new password must be at least 8 characters.", "error")
        else:
            current_user.username = username
            current_user.email = email
            if new_password:
                current_user.password_hash = generate_password_hash(
                    new_password
                )
            db.session.commit()
            flash("Profile updated successfully.", "success")
            return redirect(url_for("users.edit_profile"))

    return render_template("users/profile.html")


@user_bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
def edit_user(user_id):
    # Update a user's account details, role, or password.
    user = db.get_or_404(User, user_id)

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        role = request.form.get("role", "").strip()
        new_password = request.form.get("new_password", "")
        duplicate_username = User.query.filter(
            User.username == username,
            User.id != user.id,
        ).first()
        duplicate_email = User.query.filter(
            User.email == email,
            User.id != user.id,
        ).first()

        if not username or not email:
            flash("Username and email are required.", "error")
        elif len(username) > 50 or len(email) > 120:
            flash("Username or email is too long.", "error")
        elif role not in User.ROLES:
            flash("Select a valid role.", "error")
        elif duplicate_username:
            flash("That username is already in use.", "error")
        elif duplicate_email:
            flash("That email address is already in use.", "error")
        elif new_password and len(new_password) < 8:
            flash("The new password must be at least 8 characters.", "error")
        elif role == User.EMPLOYEE and user.employee is None:
            flash(
                "Assign an employee record before setting this account "
                "to the employee role.",
                "error",
            )
        elif user.id == current_user.id and role != user.role:
            flash("You cannot change your own role.", "error")
        elif user.role == User.ADMIN and role != User.ADMIN and (
            db.session.query(func.count(User.id))
            .filter_by(role=User.ADMIN)
            .scalar()
            <= 1
        ):
            flash("The last administrator cannot be demoted.", "error")
        else:
            user.username = username
            user.email = email
            user.role = role
            if new_password:
                user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash("User account updated successfully.", "success")
            return redirect(url_for("users.user_list"))

    return render_template(
        "users/edit.html",
        user=user,
        roles=User.ROLES,
    )


@user_bp.route("/add", methods=["GET", "POST"])
def add_user():
    # Create a new administrator or HR user account.
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
        elif role not in ACCOUNT_CREATION_ROLES:
            flash(
                "Create employee accounts from Add Employee so they are "
                "linked to an employee record.",
                "error",
            )
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

    return render_template(
        "users/add.html",
        roles=ACCOUNT_CREATION_ROLES,
    )


@user_bp.route("/<int:user_id>/role", methods=["POST"])
def update_user_role(user_id):
    # Change a user's role while protecting administrator access.
    user = db.get_or_404(User, user_id)
    role = request.form.get("role", "").strip()

    if role not in User.ROLES:
        flash("Select a valid role.", "error")
    elif role == User.EMPLOYEE and Employee.query.filter_by(
        user_id=user.id
    ).first() is None:
        flash(
            "This account has no employee record. Create or link an employee "
            "record before assigning the employee role.",
            "error",
        )
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
    # Return all user accounts as JSON.
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
