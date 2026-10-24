from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from werkzeug.security import check_password_hash, generate_password_hash

from models import db
from models.department import Department
from models.employee import Employee
from models.user import User
from routes.employee_access import delete_employee_account
from profile_storage import (
    ProfileStorageError,
    delete_profile_picture,
    profile_picture_urls,
    save_profile_picture,
)

user_bp = Blueprint("users", __name__, url_prefix="/users")
ACCOUNT_CREATION_ROLES = User.ROLES


@user_bp.before_request
def require_admin():
    # Allow only administrators, except when users edit their own profile.
    if (
        current_user.role != User.ADMIN
        and request.endpoint
        not in {"users.edit_profile", "users.edit_profile_picture"}
    ):
        abort(403)


@user_bp.route("/")
def user_list():
    # Show all user accounts.
    users = User.query.options(
        joinedload(User.employee)
    ).order_by(User.username.asc()).paginate(
        page=request.args.get("page", 1, type=int),
        per_page=50,
        error_out=False,
    )
    picture_urls = profile_picture_urls(
        [
            user.employee.profile_picture
            for user in users.items
            if user.employee and user.employee.profile_picture
        ]
    )
    return render_template(
        "users/list.html",
        users=users,
        roles=User.ROLES,
        admin_count=User.query.filter_by(role=User.ADMIN).count(),
        profile_picture_urls=picture_urls,
    )


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


@user_bp.route("/profile/picture", methods=["POST"])
def edit_profile_picture():
    employee = current_user.employee
    if employee is None:
        flash("Your account is not linked to an employee record.", "error")
        return redirect(url_for("users.edit_profile"))

    image_file = request.files.get("profile_picture")
    if not image_file or not image_file.filename:
        flash("Choose a profile picture to upload.", "error")
        return redirect(url_for("users.edit_profile"))

    new_picture, picture_error = save_profile_picture(image_file, employee.id)
    if picture_error:
        flash(picture_error, "error")
        return redirect(url_for("users.edit_profile"))

    old_picture = employee.profile_picture
    employee.profile_picture = new_picture
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        try:
            delete_profile_picture(new_picture)
        except ProfileStorageError:
            current_app.logger.exception(
                "Could not remove uncommitted profile picture from storage."
            )
        raise

    if old_picture:
        try:
            delete_profile_picture(old_picture)
        except ProfileStorageError:
            current_app.logger.warning(
                "Could not remove the previous profile picture from storage."
            )

    flash("Profile picture updated successfully.", "success")
    return redirect(url_for("users.edit_profile"))


@user_bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
def edit_user(user_id):
    # Update a user's account details, role, or password.
    user = db.get_or_404(User, user_id)

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        role = request.form.get("role", "").strip()
        new_password = request.form.get("new_password", "")
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        position = request.form.get("position", "").strip()
        department_id = request.form.get("department_id", type=int)
        salary_value = request.form.get("salary", "").strip()
        duplicate_username = User.query.filter(
            User.username == username,
            User.id != user.id,
        ).first()
        duplicate_email = User.query.filter(
            User.email == email,
            User.id != user.id,
        ).first()
        try:
            salary = Decimal(salary_value)
            if (
                not salary.is_finite()
                or salary < 0
                or salary > Decimal("99999999.99")
                or salary.quantize(Decimal("0.01")) != salary
            ):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            salary = None
        department = (
            db.session.get(Department, department_id)
            if department_id
            else None
        )

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
        elif role == User.EMPLOYEE and not all(
            (first_name, last_name, position)
        ):
            flash("Complete all required employee fields.", "error")
        elif role == User.EMPLOYEE and (
            len(first_name) > 50
            or len(last_name) > 50
            or len(position) > 100
        ):
            flash("One or more employee fields exceed their maximum length.", "error")
        elif role == User.EMPLOYEE and department is None:
            flash("Select a valid department.", "error")
        elif role == User.EMPLOYEE and salary is None:
            flash("Enter a valid, non-negative salary.", "error")
        elif role not in User.ROLES:
            flash("Select a valid role.", "error")
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
            if role == User.EMPLOYEE:
                if user.employee is None:
                    user.employee = Employee(
                        first_name=first_name,
                        last_name=last_name,
                        position=position,
                        salary=salary,
                        department=department,
                    )
                else:
                    user.employee.first_name = first_name
                    user.employee.last_name = last_name
                    user.employee.position = position
                    user.employee.salary = salary
                    user.employee.department = department
            db.session.commit()
            flash("User account updated successfully.", "success")
            return redirect(url_for("users.user_list"))

    return render_template(
        "users/edit.html",
        user=user,
        roles=User.ROLES,
        departments=Department.query.order_by(
            Department.department_name.asc()
        ).all(),
        selected_role=request.args.get("role", user.role),
    )


@user_bp.route("/add", methods=["GET", "POST"])
def add_user():
    # Create a management account or an employee account with its profile.
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "").strip()
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        position = request.form.get("position", "").strip()
        department_id = request.form.get("department_id", type=int)
        salary_value = request.form.get("salary", "").strip()

        try:
            salary = Decimal(salary_value)
            if (
                not salary.is_finite()
                or salary < 0
                or salary > Decimal("99999999.99")
                or salary.quantize(Decimal("0.01")) != salary
            ):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            salary = None

        department = (
            db.session.get(Department, department_id)
            if department_id
            else None
        )

        if not username or not email or not password:
            flash("Complete all required fields.", "error")
        elif len(username) > 50 or len(email) > 120:
            flash("Username or email is too long.", "error")
        elif len(password) < 8:
            flash("The account password must be at least 8 characters.", "error")
        elif role not in ACCOUNT_CREATION_ROLES:
            flash("Select a valid role.", "error")
        elif role == User.EMPLOYEE and not all(
            (first_name, last_name, position)
        ):
            flash("Complete all required employee fields.", "error")
        elif role == User.EMPLOYEE and (
            len(first_name) > 50
            or len(last_name) > 50
            or len(position) > 100
        ):
            flash("One or more employee fields exceed their maximum length.", "error")
        elif role == User.EMPLOYEE and department is None:
            flash("Select a valid department.", "error")
        elif role == User.EMPLOYEE and salary is None:
            flash("Enter a valid, non-negative salary.", "error")
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
            if role == User.EMPLOYEE:
                user.employee = Employee(
                    first_name=first_name,
                    last_name=last_name,
                    position=position,
                    department=department,
                    salary=salary,
                )
            db.session.add(user)
            db.session.commit()
            flash(
                "Employee account added successfully."
                if role == User.EMPLOYEE
                else "User added successfully.",
                "success",
            )
            return redirect(url_for("users.user_list"))

    return render_template(
        "users/add.html",
        roles=ACCOUNT_CREATION_ROLES,
        departments=Department.query.order_by(
            Department.department_name.asc()
        ).all(),
    )


@user_bp.route("/<int:user_id>/role", methods=["POST"])
def update_user_role(user_id):
    # Change a user's role while protecting administrator access.
    user = db.get_or_404(User, user_id)
    role = request.form.get("role", "").strip()

    if role not in User.ROLES:
        flash("Select a valid role.", "error")
    elif role == User.EMPLOYEE and user.employee is None:
        return redirect(
            url_for("users.edit_user", user_id=user.id, role=User.EMPLOYEE)
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


@user_bp.route("/<int:user_id>/delete", methods=["POST"])
def delete_user(user_id):
    user = db.get_or_404(User, user_id)

    if user.id == current_user.id:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("users.user_list"))
    if user.role == User.ADMIN and User.query.filter_by(
        role=User.ADMIN
    ).count() <= 1:
        flash("The last administrator cannot be deleted.", "error")
        return redirect(url_for("users.user_list"))

    employee = user.employee
    if employee and employee.payroll_records:
        flash(
            "This account cannot be deleted while payroll records exist. "
            "Payroll history is preserved.",
            "error",
        )
        return redirect(url_for("users.user_list"))

    if employee:
        delete_employee_account(employee)
    else:
        db.session.delete(user)
    db.session.commit()
    flash("User account deleted successfully.", "success")
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
