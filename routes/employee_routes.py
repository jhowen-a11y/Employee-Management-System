
from flask import Blueprint, render_template

from models.employee import Employee


employee_bp = Blueprint(
    "employee",
    __name__,
    url_prefix="/employees"
)


# View all employees
@employee_bp.route("/")
def employee_list():
    employees = Employee.query.all()

    return render_template(
        "employee/list.html",
        employees=employees
    )


# View an employee by ID
@employee_bp.route("/<int:employee_id>")
def employee_detail(employee_id):
    employee = Employee.query.get_or_404(employee_id)

    return render_template(
        "employees/detail.html",
        employee=employee
    )

