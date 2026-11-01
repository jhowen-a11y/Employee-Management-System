
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import joinedload
from werkzeug.security import generate_password_hash

from models import db
from models.department import Department
from models.employee import Employee
from models.user import User
from profile_storage import (
    ProfileStorageError,
    delete_profile_picture,
    profile_picture_urls,
    save_profile_picture,
)
from routes.auth_routes import admin_required
from routes.employee_access import (
    current_employee,
    delete_employee_account,
    management_required,
)


employee_bp = Blueprint(
    "employee",
    __name__,
    url_prefix="/employees"
)

# View all employees
@employee_bp.route("/")
def employee_list():
    search = request.args.get("q", "").strip()
    selected_department = request.args.get("department", "").strip()
    selected_role = request.args.get("role", "").strip()
    sort = request.args.get("sort", "name").strip()
    direction = request.args.get("direction", "asc").strip().lower()
    sort_fields = {
        "name": (Employee.last_name, Employee.first_name),
        "employee_id": (Employee.id,),
        "department": (Department.department_name,),
        "role": (User.role,),
        "created_at": (Employee.created_at,),
        "username": (User.username,),
    }
    if sort not in sort_fields:
        sort = "name"
    if direction not in {"asc", "desc"}:
        direction = "asc"

    sort_expressions = [
        expression.asc() if direction == "asc" else expression.desc()
        for expression in sort_fields[sort]
    ]
    department_query = Department.query
    if current_user.role == User.EMPLOYEE:
        employee = current_employee()
        department_query = department_query.filter_by(
            id=employee.department_id if employee else None
        )
    departments = department_query.order_by(
        Department.department_name.asc()
    ).all()

    if current_user.role in (User.ADMIN, User.HR):
        user_query = User.query.outerjoin(User.employee).outerjoin(
            Employee.department
        )
        if search:
            search_pattern = f"%{search}%"
            search_filters = [
                User.username.ilike(search_pattern),
                User.email.ilike(search_pattern),
                User.role.ilike(search_pattern),
                Department.department_name.ilike(search_pattern),
                Employee.first_name.ilike(search_pattern),
                Employee.last_name.ilike(search_pattern),
                (Employee.first_name + " " + Employee.last_name).ilike(search_pattern),
            ]
            if search.isdecimal():
                search_filters.append(
                    cast(Employee.id, String).ilike(search_pattern)
                )
            user_query = user_query.filter(or_(*search_filters))
        if selected_department:
            if not selected_department.isdecimal():
                selected_department = ""
            else:
                user_query = user_query.filter(
                    Employee.department_id == int(selected_department)
                )
        if selected_role in User.ROLES:
            user_query = user_query.filter(User.role == selected_role)
        else:
            selected_role = ""
        users = user_query.options(
            joinedload(User.employee).joinedload(Employee.department)
        ).order_by(*sort_expressions, User.id.asc()).paginate(
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
            "employee/list.html",
            employees=[],
            users=users,
            profile_picture_urls=picture_urls,
            search=search,
            sort=sort,
            direction=direction,
            departments=departments,
            selected_department=selected_department,
            selected_role=selected_role,
        )

    employee_query = Employee.query

    if current_user.role == User.EMPLOYEE:
        employee_query = employee_query.filter_by(user_id=current_user.id)
    elif current_user.role == User.HR:
        employee_query = employee_query.join(Employee.user).filter(
            User.role == User.EMPLOYEE
        )

    employee_query = employee_query.join(Employee.user).join(
        Employee.department
    )
    if search:
        search_pattern = f"%{search}%"
        search_filters = [
            Employee.first_name.ilike(search_pattern),
            Employee.last_name.ilike(search_pattern),
            Employee.position.ilike(search_pattern),
            Department.department_name.ilike(search_pattern),
            User.username.ilike(search_pattern),
            User.email.ilike(search_pattern),
            (Employee.first_name + " " + Employee.last_name).ilike(search_pattern),
        ]
        if search.isdecimal():
            search_filters.append(
                cast(Employee.id, String).ilike(search_pattern)
            )
        employee_query = employee_query.filter(or_(*search_filters))
    if selected_department and selected_department.isdecimal():
        employee_query = employee_query.filter(
            Employee.department_id == int(selected_department)
        )
    elif selected_department:
        selected_department = ""
    if selected_role in User.ROLES:
        employee_query = employee_query.filter(User.role == selected_role)
    else:
        selected_role = ""

    employees = employee_query.order_by(
        *sort_expressions, Employee.id.asc()
    ).options(
        joinedload(Employee.department),
        joinedload(Employee.user),
    ).paginate(
        page=request.args.get("page", 1, type=int),
        per_page=50,
        error_out=False,
    )
    picture_urls = profile_picture_urls(
        [
            employee.profile_picture
            for employee in employees.items
            if employee.profile_picture
        ]
    )

    return render_template(
        "employee/list.html",
        employees=employees,
        users=None,
        profile_picture_urls=picture_urls,
        search=search,
        sort=sort,
        direction=direction,
        departments=departments,
        selected_department=selected_department,
        selected_role=selected_role,
    )


# Add an employee
@employee_bp.route("/add", methods=["GET", "POST"])
@management_required
def add_employee():
    departments = Department.query.order_by(
        Department.department_name.asc()
    ).all()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
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

        if not all((username, email, password, first_name, last_name, position)):
            flash("Complete all required fields.", "error")
        elif (
            len(username) > 50
            or len(email) > 120
            or len(first_name) > 50
            or len(last_name) > 50
            or len(position) > 100
        ):
            flash("One or more employee fields exceed their maximum length.", "error")
        elif len(password) < 8:
            flash("The account password must be at least 8 characters.", "error")
        elif salary is None:
            flash("Enter a valid, non-negative salary.", "error")
        elif not department_id or db.session.get(Department, department_id) is None:
            flash("Select a valid department.", "error")
        elif User.query.filter_by(username=username).first():
            flash("That username is already in use.", "error")
        elif User.query.filter_by(email=email).first():
            flash("That email address is already in use.", "error")
        else:
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                role=User.EMPLOYEE,
            )

            employee = Employee(
                user=user,
                first_name=first_name,
                last_name=last_name,
                position=position,
                salary=salary,
                department_id=department_id,
            )

            db.session.add(employee)
            db.session.commit()

            flash("Employee added successfully.", "success")
            return redirect(url_for("employee.employee_list"))

    return render_template("employee/add.html", departments=departments)


# Link an existing user to an employee record
@employee_bp.route("/link-user/<int:user_id>", methods=["GET", "POST"])
@admin_required
def link_user_to_employee(user_id):
    user = db.get_or_404(User, user_id)

    if user.employee:
        return redirect(
            url_for("employee.edit_employee", employee_id=user.employee.id)
        )

    departments = Department.query.order_by(
        Department.department_name.asc()
    ).all()

    if request.method == "POST":
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

        if not all((first_name, last_name, position)):
            flash("Complete all required employee fields.", "error")
        elif (
            len(first_name) > 50
            or len(last_name) > 50
            or len(position) > 100
        ):
            flash("One or more employee fields exceed their maximum length.", "error")
        elif salary is None:
            flash("Enter a valid, non-negative salary.", "error")
        elif department is None:
            flash("Select a valid department.", "error")
        else:
            employee = Employee(
                user=user,
                first_name=first_name,
                last_name=last_name,
                position=position,
                salary=salary,
                department=department,
            )

            db.session.add(employee)
            db.session.commit()

            flash(
                f"{user.username} was assigned to {department.department_name.upper()}.",
                "success",
            )

            return redirect(
                url_for("employee.employee_detail", employee_id=employee.id)
            )

    return render_template(
        "employee/link_user.html",
        user=user,
        departments=departments,
    )


# View an employee by ID
@employee_bp.route("/<int:employee_id>")
def employee_detail(employee_id):
    employee_query = Employee.query.filter_by(id=employee_id)

    if current_user.role == User.EMPLOYEE:
        own_employee = current_employee()
        employee_query = employee_query.filter_by(
            id=own_employee.id if own_employee else None
        )
    elif current_user.role == User.HR:
        employee_query = employee_query.join(Employee.user).filter(
            User.role == User.EMPLOYEE
        )

    employee = employee_query.first_or_404()

    return render_template(
        "employee/detail.html",
        employee=employee,
    )


# Edit an employee and upload their profile picture
@employee_bp.route("/<int:employee_id>/edit", methods=["GET", "POST"])
@management_required
def edit_employee(employee_id):
    employee_query = Employee.query.filter_by(id=employee_id)

    if current_user.role == User.HR:
        employee_query = employee_query.join(Employee.user).filter(
            User.role == User.EMPLOYEE
        )

    employee = employee_query.first_or_404()

    departments = Department.query.order_by(
        Department.department_name.asc()
    ).all()

    if request.method == "POST":
        is_admin = current_user.role == User.ADMIN

        username = (
            request.form.get("username", "").strip()
            if is_admin
            else employee.user.username
        )
        email = (
            request.form.get("email", "").strip()
            if is_admin
            else employee.user.email
        )

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

        duplicate_username = (
            User.query.filter(
                User.username == username,
                User.id != employee.user_id,
            ).first()
            if is_admin
            else None
        )

        duplicate_email = (
            User.query.filter(
                User.email == email,
                User.id != employee.user_id,
            ).first()
            if is_admin
            else None
        )

        if not all((first_name, last_name, position)) or (
            is_admin and not all((username, email))
        ):
            flash("Complete all required fields.", "error")
        elif (
            (is_admin and (len(username) > 50 or len(email) > 120))
            or len(first_name) > 50
            or len(last_name) > 50
            or len(position) > 100
        ):
            flash("One or more employee fields exceed their maximum length.", "error")
        elif salary is None:
            flash("Enter a valid, non-negative salary.", "error")
        elif not department_id or db.session.get(Department, department_id) is None:
            flash("Select a valid department.", "error")
        elif duplicate_username:
            flash("That username is already in use.", "error")
        elif duplicate_email:
            flash("That email address is already in use.", "error")
        else:
            new_picture = None
            picture_error = None

            picture_file = request.files.get("profile_picture")

            if picture_file and picture_file.filename:
                new_picture, picture_error = save_profile_picture(
                    picture_file,
                    employee.id,
                )

            if picture_error:
                flash(picture_error, "error")
            else:
                old_picture = employee.profile_picture

                if is_admin:
                    employee.user.username = username
                    employee.user.email = email

                employee.first_name = first_name
                employee.last_name = last_name
                employee.position = position
                employee.salary = salary
                employee.department_id = department_id

                if new_picture:
                    employee.profile_picture = new_picture

                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

                    if new_picture:
                        try:
                            delete_profile_picture(new_picture)
                        except ProfileStorageError:
                            current_app.logger.exception(
                                "Could not remove uncommitted profile picture "
                                "from Supabase Storage."
                            )

                    raise

                # Remove the previous image only after the new one is saved.
                if new_picture and old_picture:
                    try:
                        delete_profile_picture(old_picture)
                    except ProfileStorageError:
                        current_app.logger.warning(
                            "Could not remove old profile picture from "
                            "Supabase Storage."
                        )

                flash("Employee updated successfully.", "success")

                return redirect(
                    url_for("employee.employee_detail", employee_id=employee.id)
                )

    return render_template(
        "employee/edit.html",
        employee=employee,
        departments=departments,
    )


# Delete an employee
@employee_bp.route("/<int:employee_id>/delete", methods=["POST"])
@admin_required
def delete_employee(employee_id):
    employee = db.get_or_404(Employee, employee_id)
    user = employee.user

    if user.id == current_user.id:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("employee.employee_list"))

    if user.role == User.ADMIN and User.query.filter_by(
        role=User.ADMIN
    ).count() <= 1:
        flash("The last administrator cannot be deleted.", "error")
        return redirect(url_for("employee.employee_list"))

    if employee.payroll_records:
        flash(
            "This employee cannot be deleted while payroll records exist. "
            "Payroll history is preserved.",
            "error",
        )
        return redirect(url_for("employee.employee_list"))

    delete_employee_account(employee)
    db.session.commit()

    flash("Employee and linked account deleted successfully.", "success")
    return redirect(url_for("employee.employee_list"))
