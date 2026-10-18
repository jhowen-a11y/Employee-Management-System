
from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import selectinload
from werkzeug.security import generate_password_hash

from models import db
from models.department import Department
from models.employee import Employee
from models.user import User
from routes.auth_routes import admin_required
from routes.employee_access import current_employee


employee_bp = Blueprint(
    "employee",
    __name__,
    url_prefix="/employees"
)


# View all employees
@employee_bp.route("/")
def employee_list():
    if current_user.role in (User.ADMIN, User.HR):
        users = User.query.options(
            selectinload(User.employee).selectinload(Employee.department)
        ).order_by(User.username.asc()).paginate(
            page=request.args.get("page", 1, type=int),
            per_page=50,
            error_out=False,
        )
        return render_template(
            "employee/list.html",
            employees=[],
            users=users,
        )

    employee_query = Employee.query
    if current_user.role == User.EMPLOYEE:
        employee_query = employee_query.filter_by(user_id=current_user.id)
    employees = employee_query.order_by(
        Employee.last_name.asc(),
        Employee.first_name.asc(),
        Employee.id.asc(),
    ).options(
        selectinload(Employee.department),
        selectinload(Employee.user),
    ).paginate(
        page=request.args.get("page", 1, type=int),
        per_page=50,
        error_out=False,
    )

    return render_template(
        "employee/list.html",
        employees=employees,
        users=None,
    )


@employee_bp.route("/add", methods=["GET", "POST"])
@admin_required
def add_employee():
    # Create an employee and its associated user account.
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
                password_hash=generate_password_hash(password)
            )
            employee = Employee(
                user=user,
                first_name=first_name,
                last_name=last_name,
                position=position,
                salary=salary,
                department_id=department_id
            )
            db.session.add(employee)
            db.session.commit()

            flash("Employee added successfully.", "success")
            return redirect(url_for("employee.employee_list"))

    return render_template("employee/add.html", departments=departments)


@employee_bp.route("/link-user/<int:user_id>", methods=["GET", "POST"])
@admin_required
def link_user_to_employee(user_id):
    # Create an employee record linked to an existing user account.
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
                f"{user.username} was assigned to {department.department_name}.",
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
    employee = employee_query.first_or_404()

    return render_template(
        "employee/detail.html",
        employee=employee
    )


@employee_bp.route("/<int:employee_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_employee(employee_id):
    # Update an employee's details and associated user account.
    employee = db.get_or_404(Employee, employee_id)
    departments = Department.query.order_by(
        Department.department_name.asc()
    ).all()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
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

        duplicate_username = User.query.filter(
            User.username == username,
            User.id != employee.user_id
        ).first()
        duplicate_email = User.query.filter(
            User.email == email,
            User.id != employee.user_id
        ).first()

        if not all((username, email, first_name, last_name, position)):
            flash("Complete all required fields.", "error")
        elif (
            len(username) > 50
            or len(email) > 120
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
            employee.user.username = username
            employee.user.email = email
            employee.first_name = first_name
            employee.last_name = last_name
            employee.position = position
            employee.salary = salary
            employee.department_id = department_id
            db.session.commit()

            flash("Employee updated successfully.", "success")
            return redirect(
                url_for("employee.employee_detail", employee_id=employee.id)
            )

    return render_template(
        "employee/edit.html",
        employee=employee,
        departments=departments
    )
