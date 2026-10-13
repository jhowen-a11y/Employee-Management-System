
from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user

from models.employee import Employee

employee_bp = Blueprint(
    "employee",
    __name__,
    url_prefix="/employees"
)


# View all employees
@employee_bp.route("/")
@login_required
def employee_list():
    employees = Employee.query.all()

    return render_template(
        "employees/list.html",
        employees=employees
    )


# View an employee by ID
@employee_bp.route("/<int:employee_id>")
@login_required
def employee_detail(employee_id):
    employee = Employee.query.get_or_404(employee_id)

    return render_template(
        "employees/detail.html",
        employee=employee
    )


# View the currently logged-in user's employee profile
@employee_bp.route("/me")
@login_required
def my_profile():
    employee = current_user.employee

    if employee is None:
        abort(404, description="Employee profile not found.")

    return render_template(
        "employees/detail.html",
        employee=employee
    )
