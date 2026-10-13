
from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from models import db
from models.department import Department
from models.employee import Employee
from models.user import User


employee_bp = Blueprint(
    "employee",
    __name__,
    url_prefix="/employees"
)


# View all employees
@employee_bp.route("/")
def employee_list():
    employees = Employee.query.order_by(
        Employee.last_name.asc(),
        Employee.first_name.asc()
    ).all()

    return render_template(
        "employee/list.html",
        employees=employees
    )


@employee_bp.route("/add", methods=["GET", "POST"])
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
            if not salary.is_finite() or salary < 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            salary = None

        if not all((username, email, password, first_name, last_name, position)):
            flash("Complete all required fields.", "error")
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


# View an employee by ID
@employee_bp.route("/<int:employee_id>")
def employee_detail(employee_id):
    employee = Employee.query.get_or_404(employee_id)

    return render_template(
        "employee/detail.html",
        employee=employee
    )


@employee_bp.route("/<int:employee_id>/edit", methods=["GET", "POST"])
def edit_employee(employee_id):
    employee = Employee.query.get_or_404(employee_id)
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
            if not salary.is_finite() or salary < 0:
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
