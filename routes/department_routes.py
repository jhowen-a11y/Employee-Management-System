
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user

from models import db
from models.department import Department
from models.user import User
from routes.employee_access import current_employee, management_required
from profile_storage import profile_picture_urls

department_bp = Blueprint(
    "department",
    __name__,
    url_prefix="/departments"
)


# View all departments
@department_bp.route("/")
def department_list():
    department_query = Department.query
    if current_user.role == User.EMPLOYEE:
        employee = current_employee()
        department_query = department_query.filter_by(
            id=employee.department_id if employee else None
        )
    departments = department_query.order_by(
        Department.department_name.asc()
    ).all()

    return render_template(
        "departments/list.html",
        departments=departments
    )


# View one department
@department_bp.route("/<int:department_id>")
def department_detail(department_id):
    department_query = Department.query.filter_by(id=department_id)
    if current_user.role == User.EMPLOYEE:
        employee = current_employee()
        department_query = department_query.filter_by(
            id=employee.department_id if employee else None
        )
    department = department_query.first_or_404()
    picture_urls = profile_picture_urls(
        [
            employee.profile_picture
            for employee in department.employees
            if employee.profile_picture
        ]
    )

    return render_template(
        "departments/detail.html",
        department=department,
        profile_picture_urls=picture_urls,
    )


# Add a department
@department_bp.route("/add", methods=["GET", "POST"])
@management_required
def add_department():
    if request.method == "POST":
        department_name = request.form.get(
            "department_name", ""
        ).strip()

        description = request.form.get(
            "description", ""
        ).strip()

        if not department_name or len(department_name) > 100:
            flash("Department name must be between 1 and 100 characters.", "error")
            return render_template("departments/add.html")
        if len(description) > 255:
            flash("Department description cannot exceed 255 characters.", "error")
            return render_template("departments/add.html")

        # Prevent duplicate department names
        existing_department = Department.query.filter_by(
            department_name=department_name
        ).first()

        if existing_department:
            flash("This department already exists.", "error")
            return render_template("departments/add.html")

        department = Department(
            department_name=department_name,
            description=description or None
        )

        db.session.add(department)
        db.session.commit()

        flash("Department added successfully!", "success")
        return redirect(url_for("department.department_list"))

    return render_template("departments/add.html")


# Edit a department
@department_bp.route("/<int:department_id>/edit", methods=["GET", "POST"])
@management_required
def edit_department(department_id):
    department = db.get_or_404(Department, department_id)

    if request.method == "POST":
        department_name = request.form.get(
            "department_name", ""
        ).strip()

        description = request.form.get(
            "description", ""
        ).strip()

        if not department_name or len(department_name) > 100:
            flash("Department name must be between 1 and 100 characters.", "error")
            return render_template(
                "departments/edit.html", department=department
            )
        if len(description) > 255:
            flash("Department description cannot exceed 255 characters.", "error")
            return render_template(
                "departments/edit.html", department=department
            )

        existing_department = Department.query.filter(
            Department.department_name == department_name,
            Department.id != department.id
        ).first()

        if existing_department:
            flash("This department name is already in use.", "error")
            return render_template(
                "departments/edit.html", department=department
            )

        department.department_name = department_name
        department.description = description or None

        db.session.commit()

        flash("Department updated successfully!", "success")
        return redirect(url_for("department.department_list"))

    return render_template(
        "departments/edit.html",
        department=department
    )


# Delete a department
@department_bp.route("/<int:department_id>/delete", methods=["POST"])
@management_required
def delete_department(department_id):
    department = db.get_or_404(Department, department_id)

    # Don't delete a department that still has employees
    if department.employees:
        flash(
            "Cannot delete this department because employees are assigned to it.",
            "error"
        )
        return redirect(url_for("department.department_list"))

    db.session.delete(department)
    db.session.commit()

    flash("Department deleted successfully!", "success")
    return redirect(url_for("department.department_list"))
