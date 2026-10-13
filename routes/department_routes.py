
from flask import Blueprint, render_template, request, redirect, url_for, flash

from models import db
from models.department import Department

department_bp = Blueprint(
    "department",
    __name__,
    url_prefix="/departments"
)


# View all departments
@department_bp.route("/")
def department_list():
    departments = Department.query.order_by(
        Department.department_name.asc()
    ).all()

    return render_template(
        "departments/list.html",
        departments=departments
    )


# View one department
@department_bp.route("/<int:department_id>")
def department_detail(department_id):
    department = Department.query.get_or_404(department_id)

    return render_template(
        "departments/detail.html",
        department=department
    )


# Add a department
@department_bp.route("/add", methods=["GET", "POST"])
def add_department():
    if request.method == "POST":
        department_name = request.form.get(
            "department_name", ""
        ).strip()

        description = request.form.get(
            "description", ""
        ).strip()

        if not department_name:
            flash("Department name is required.", "error")
            return redirect(url_for("department.add_department"))

        # Prevent duplicate department names
        existing_department = Department.query.filter_by(
            department_name=department_name
        ).first()

        if existing_department:
            flash("This department already exists.", "error")
            return redirect(url_for("department.add_department"))

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
def edit_department(department_id):
    department = Department.query.get_or_404(department_id)

    if request.method == "POST":
        department_name = request.form.get(
            "department_name", ""
        ).strip()

        description = request.form.get(
            "description", ""
        ).strip()

        if not department_name:
            flash("Department name is required.", "error")
            return redirect(
                url_for("department.edit_department",
                        department_id=department.id)
            )

        existing_department = Department.query.filter(
            Department.department_name == department_name,
            Department.id != department.id
        ).first()

        if existing_department:
            flash("This department name is already in use.", "error")
            return redirect(
                url_for("department.edit_department",
                        department_id=department.id)
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
def delete_department(department_id):
    department = Department.query.get_or_404(department_id)

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
