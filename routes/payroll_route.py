
from flask import abort, Blueprint, current_app, jsonify, render_template, request, redirect, url_for, flash
from datetime import date
from decimal import Decimal, InvalidOperation
from flask_login import current_user
from sqlalchemy import String, cast, func, insert, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from models import db
from models.payroll import Payroll
from models.employee import Employee
from models.record_audit import RecordAudit
from models.user import User
from profile_storage import profile_picture_urls
from routes.employee_access import management_required
from services.payroll_deductions import (
    attendance_deduction_schema_available,
    calculate_attendance_deductions,
    serialize_deduction_preview,
)

payroll_bp = Blueprint(
    "payroll",
    __name__,
    url_prefix="/payroll"
)

MAX_PAYROLL_AMOUNT = Decimal("99999999.99")


def read_money(value, default=None):
    """Convert a form value into a non-negative, two-decimal amount."""
    if value is None or value == "":
        return default

    try:
        amount = Decimal(value.strip())
        if (
            not amount.is_finite()
            or amount < 0
            or amount > MAX_PAYROLL_AMOUNT
        ):
            return None
        rounded_amount = amount.quantize(Decimal("0.01"))
        if rounded_amount != amount:
            return None
        return rounded_amount
    except InvalidOperation:
        return None


def read_date(value):
    # Convert a form value to a date, returning None when it is invalid.
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def payroll_snapshot(payroll, include_breakdown=True):
    snapshot = {
        "employee_id": payroll.employee_id,
        "pay_period_start": payroll.pay_period_start.isoformat(),
        "pay_period_end": payroll.pay_period_end.isoformat(),
        "basic_salary": str(payroll.basic_salary),
        "allowances": str(payroll.allowances),
        "deductions": str(payroll.deductions),
        "net_pay": str(payroll.net_pay),
        "payment_date": (
            payroll.payment_date.isoformat() if payroll.payment_date else None
        ),
    }
    if include_breakdown:
        snapshot.update(
            absence_days=payroll.absence_days,
            late_minutes=payroll.late_minutes,
            absence_deduction=(
                str(payroll.absence_deduction)
                if payroll.absence_deduction is not None
                else None
            ),
            late_deduction=(
                str(payroll.late_deduction)
                if payroll.late_deduction is not None
                else None
            ),
        )
    return snapshot


def has_duplicate_payroll(employee_id, period_start, period_end, exclude_id=None):
    query = Payroll.query.filter_by(
        employee_id=employee_id,
        pay_period_start=period_start,
        pay_period_end=period_end,
    )
    if exclude_id is not None:
        query = query.filter(Payroll.id != exclude_id)
    return query.first() is not None


def render_payroll_add(employees):
    return render_template(
        "payroll/add.html",
        employees=employees,
        deduction_breakdown_available=attendance_deduction_schema_available(),
    )


# View all payroll records
@payroll_bp.route("/")
@management_required
def payroll_list():
    search = request.args.get("q", "").strip()
    period_from_value = request.args.get("from", "").strip()
    period_to_value = request.args.get("to", "").strip()
    period_from = read_date(period_from_value) if period_from_value else None
    period_to = read_date(period_to_value) if period_to_value else None
    if (period_from_value and period_from is None) or (period_to_value and period_to is None):
        abort(400, description="Enter valid payroll period dates.")
    if period_from and period_to and period_to < period_from:
        abort(400, description="The end date cannot be earlier than the start date.")
    status = request.args.get("status", "").strip()
    if status not in {"", "paid", "pending"}:
        abort(400, description="Select a valid payroll status.")
    sort = request.args.get("sort", "employee").strip()
    direction = request.args.get("direction", "desc").strip().lower()
    gross_pay = Payroll.basic_salary + Payroll.allowances
    sort_fields = {
        "employee": (Employee.last_name, Employee.first_name),
        "period": (Payroll.pay_period_start,),
        "gross": (gross_pay,),
        "deductions": (Payroll.deductions,),
        "net": (Payroll.net_pay,),
        "payment_date": (Payroll.payment_date,),
    }
    if sort not in sort_fields:
        sort = "employee"
    if direction not in {"asc", "desc"}:
        direction = "desc"
    sort_expressions = [
        expression.asc() if direction == "asc" else expression.desc()
        for expression in sort_fields[sort]
    ]

    query = Payroll.query.join(Payroll.employee)
    if search:
        search_pattern = f"%{search}%"
        search_filters = [
            Employee.first_name.ilike(search_pattern),
            Employee.last_name.ilike(search_pattern),
            (Employee.first_name + " " + Employee.last_name).ilike(search_pattern),
        ]
        if search.isdecimal():
            search_filters.extend([
                cast(Employee.id, String).ilike(search_pattern),
                Payroll.pay_period_start.cast(String).ilike(search_pattern),
                Payroll.pay_period_end.cast(String).ilike(search_pattern),
            ])
        else:
            search_filters.extend([
                Payroll.pay_period_start.cast(String).ilike(search_pattern),
                Payroll.pay_period_end.cast(String).ilike(search_pattern),
            ])
        query = query.filter(or_(*search_filters))
    if period_from:
        query = query.filter(Payroll.pay_period_end >= period_from)
    if period_to:
        query = query.filter(Payroll.pay_period_start <= period_to)
    if status == "paid":
        query = query.filter(Payroll.payment_date.is_not(None))
    elif status == "pending":
        query = query.filter(Payroll.payment_date.is_(None))

    payroll_records = query.order_by(
        *sort_expressions, Payroll.id.desc()
    ).options(
        joinedload(Payroll.employee)
    ).paginate(
        page=request.args.get("page", 1, type=int),
        per_page=50,
        error_out=False,
        count=False,
    )
    payroll_records.total = query.order_by(None).with_entities(
        func.count(Payroll.id)
    ).scalar()
    picture_urls = profile_picture_urls(
        [
            payroll.employee.profile_picture
            for payroll in payroll_records.items
            if payroll.employee.profile_picture
        ]
    )

    return render_template(
        "payroll/list.html",
        payroll_records=payroll_records,
        profile_picture_urls=picture_urls,
        search=search,
        period_from=period_from_value,
        period_to=period_to_value,
        status=status,
        sort=sort,
        direction=direction,
    )


# View one payroll record
@payroll_bp.route("/<int:payroll_id>")
@management_required
def payroll_detail(payroll_id):
    payroll = db.get_or_404(Payroll, payroll_id)
    payroll_audits = RecordAudit.query.filter_by(
        record_type="payroll",
        record_id=payroll.id,
    ).order_by(RecordAudit.created_at.desc(), RecordAudit.id.desc()).all()

    return render_template(
        "payroll/detail.html",
        payroll=payroll,
        payroll_audits=payroll_audits,
        deduction_breakdown_available=attendance_deduction_schema_available(),
    )


@payroll_bp.route("/deduction-preview")
@management_required
def deduction_preview():
    employee_id = request.args.get("employee_id", type=int)
    period_start = read_date(request.args.get("pay_period_start"))
    period_end = read_date(request.args.get("pay_period_end"))
    employee = db.session.get(Employee, employee_id) if employee_id else None
    salary_value = request.args.get("basic_salary")
    basic_salary = (
        read_money(salary_value)
        if salary_value not in (None, "")
        else (read_money(str(employee.salary)) if employee else None)
    )
    allowances = read_money(request.args.get("allowances", "0.00"))

    if employee is None or not period_start or not period_end:
        return jsonify({"error": "Select an employee and valid pay period."}), 400
    if period_end < period_start:
        return jsonify({"error": "Pay period end cannot be before its start."}), 400
    if basic_salary is None or allowances is None:
        return jsonify({"error": "Enter valid salary and allowance amounts."}), 400
    if basic_salary + allowances > MAX_PAYROLL_AMOUNT:
        return jsonify({"error": "Salary plus allowances exceeds the supported amount."}), 400

    try:
        calculation = calculate_attendance_deductions(
            employee.id,
            period_start,
            period_end,
            basic_salary,
        )
    except ValueError:
        current_app.logger.exception("Payroll schedule configuration is invalid.")
        return jsonify({"error": "Payroll schedule settings are invalid."}), 503

    return jsonify(serialize_deduction_preview(calculation, basic_salary, allowances))


# Add a payroll record
@payroll_bp.route("/add", methods=["GET", "POST"])
@management_required
def add_payroll():
    employees = Employee.query.order_by(Employee.last_name).all()

    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        period_start = read_date(request.form.get("pay_period_start"))
        period_end = read_date(request.form.get("pay_period_end"))
        payment_date_value = request.form.get("payment_date", "").strip()

        basic_salary = read_money(request.form.get("basic_salary"))
        allowances = read_money(request.form.get("allowances"), Decimal("0.00"))
        payment_date = (
            read_date(payment_date_value) if payment_date_value else None
        )

        employee = db.session.get(Employee, employee_id) if employee_id else None

        if employee is None:
            flash("Please select a valid employee.", "error")
        elif not period_start or not period_end:
            flash("Please enter valid pay period dates.", "error")
        elif period_end < period_start:
            flash("Pay period end cannot be before its start.", "error")
        elif payment_date_value and not payment_date:
            flash("Please enter a valid payment date.", "error")
        elif basic_salary is None or allowances is None:
            flash("Enter valid payroll amounts with at most two decimals.", "error")
        elif basic_salary + allowances > MAX_PAYROLL_AMOUNT:
            flash("Salary plus allowances exceeds the supported amount.", "error")
        elif has_duplicate_payroll(employee.id, period_start, period_end):
            flash("A payroll record already exists for this employee and pay period.", "error")
        else:
            try:
                calculation = calculate_attendance_deductions(
                    employee.id,
                    period_start,
                    period_end,
                    basic_salary,
                )
            except ValueError:
                current_app.logger.exception(
                    "Payroll schedule configuration is invalid."
                )
                flash("Payroll schedule settings are invalid. Contact an administrator.", "error")
                return render_payroll_add(employees)
            deductions = calculation["total_deductions"]
            if deductions > basic_salary + allowances:
                flash("Attendance deductions exceed salary plus allowances.", "error")
            else:
                payroll_values = {
                    "employee_id": employee.id,
                    "pay_period_start": period_start,
                    "pay_period_end": period_end,
                    "basic_salary": basic_salary,
                    "allowances": allowances,
                    "deductions": deductions,
                    "net_pay": basic_salary + allowances - deductions,
                    "payment_date": payment_date,
                }
                if attendance_deduction_schema_available():
                    payroll_values.update(
                        absence_days=calculation["absence_days"],
                        late_minutes=calculation["late_minutes"],
                        absence_deduction=calculation["absence_deduction"],
                        late_deduction=calculation["late_deduction"],
                    )

                try:
                    db.session.execute(insert(Payroll).values(**payroll_values))
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    if not has_duplicate_payroll(
                        employee.id, period_start, period_end
                    ):
                        raise
                    flash(
                        "A payroll record already exists for this employee and pay period.",
                        "error",
                    )
                    return render_payroll_add(employees)

                if attendance_deduction_schema_available():
                    flash("Payroll record added successfully!", "success")
                else:
                    flash(
                        "Payroll saved with the calculated total. Apply the pending "
                        "database migration to save its deduction breakdown.",
                        "warning",
                    )
                return redirect(url_for("payroll.payroll_list"))

        return render_payroll_add(employees)

    return render_payroll_add(employees)


# Edit a payroll record
@payroll_bp.route("/<int:payroll_id>/edit", methods=["GET", "POST"])
@management_required
def edit_payroll(payroll_id):
    payroll = db.get_or_404(Payroll, payroll_id)
    if payroll.payment_date is not None:
        abort(
            409,
            description=(
                "Paid payroll records are locked. An administrator must use "
                "the audited correction workflow."
            ),
        )
    employees = Employee.query.order_by(Employee.last_name).all()
    breakdown_schema_available = attendance_deduction_schema_available()

    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        period_start = read_date(request.form.get("pay_period_start"))
        period_end = read_date(request.form.get("pay_period_end"))
        payment_date_value = request.form.get("payment_date", "").strip()
        basic_salary = read_money(request.form.get("basic_salary"))
        allowances = read_money(request.form.get("allowances"), Decimal("0.00"))
        automatic_deductions = (
            breakdown_schema_available and payroll.absence_deduction is not None
        )
        deductions = (
            None
            if automatic_deductions
            else read_money(request.form.get("deductions"), Decimal("0.00"))
        )
        payment_date = (
            read_date(payment_date_value) if payment_date_value else None
        )
        employee = db.session.get(Employee, employee_id) if employee_id else None

        if employee is None:
            flash("Please select a valid employee.", "error")
        elif not period_start or not period_end:
            flash("Please enter valid pay period dates.", "error")
        elif period_end < period_start:
            flash("Pay period end cannot be before its start.", "error")
        elif payment_date_value and not payment_date:
            flash("Please enter a valid payment date.", "error")
        elif basic_salary is None or allowances is None or (
            not automatic_deductions and deductions is None
        ):
            flash("Enter valid payroll amounts with at most two decimals.", "error")
        elif deductions is not None and deductions > basic_salary + allowances:
            flash("Deductions cannot exceed salary plus allowances.", "error")
        elif basic_salary + allowances > MAX_PAYROLL_AMOUNT:
            flash("Salary plus allowances exceeds the supported amount.", "error")
        elif has_duplicate_payroll(
            employee.id, period_start, period_end, exclude_id=payroll.id
        ):
            flash("A payroll record already exists for this employee and pay period.", "error")
        else:
            calculation = None
            if automatic_deductions:
                try:
                    calculation = calculate_attendance_deductions(
                        employee.id, period_start, period_end, basic_salary
                    )
                except ValueError:
                    current_app.logger.exception(
                        "Payroll schedule configuration is invalid."
                    )
                    flash("Payroll schedule settings are invalid. Contact an administrator.", "error")
                    return render_template(
                        "payroll/edit.html",
                        payroll=payroll,
                        employees=employees,
                        automatic_deductions=automatic_deductions,
                    )
                deductions = calculation["total_deductions"]
            if deductions > basic_salary + allowances:
                flash("Attendance deductions exceed salary plus allowances.", "error")
                return render_template(
                    "payroll/edit.html",
                    payroll=payroll,
                    employees=employees,
                    automatic_deductions=automatic_deductions,
                )
            values = {
                "employee_id": employee.id,
                "pay_period_start": period_start,
                "pay_period_end": period_end,
                "basic_salary": basic_salary,
                "allowances": allowances,
                "deductions": deductions,
                "net_pay": basic_salary + allowances - deductions,
                "payment_date": payment_date,
            }
            if calculation:
                values.update(
                    absence_days=calculation["absence_days"],
                    late_minutes=calculation["late_minutes"],
                    absence_deduction=calculation["absence_deduction"],
                    late_deduction=calculation["late_deduction"],
                )
            statement = update(Payroll).where(
                    Payroll.id == payroll.id,
                    Payroll.payment_date.is_(None),
                    Payroll.employee_id == payroll.employee_id,
                    Payroll.pay_period_start == payroll.pay_period_start,
                    Payroll.pay_period_end == payroll.pay_period_end,
                    Payroll.basic_salary == payroll.basic_salary,
                    Payroll.allowances == payroll.allowances,
                    Payroll.deductions == payroll.deductions,
                    Payroll.net_pay == payroll.net_pay,
            )
            if breakdown_schema_available:
                statement = statement.where(
                    Payroll.absence_days == payroll.absence_days,
                    Payroll.late_minutes == payroll.late_minutes,
                    Payroll.absence_deduction == payroll.absence_deduction,
                    Payroll.late_deduction == payroll.late_deduction,
                )
            result = db.session.execute(statement.values(**values))
            if result.rowcount != 1:
                db.session.rollback()
                abort(
                    409,
                    description="This payroll record changed. Reload before editing.",
                )
            db.session.commit()
            flash("Payroll record updated successfully!", "success")
            return redirect(url_for("payroll.payroll_list"))

    return render_template(
        "payroll/edit.html",
        payroll=payroll,
        employees=employees,
        automatic_deductions=(
            breakdown_schema_available and payroll.absence_deduction is not None
        ),
    )


@payroll_bp.route("/<int:payroll_id>/correct", methods=["GET", "POST"])
@management_required
def correct_paid_payroll(payroll_id):
    if current_user.role != User.ADMIN:
        abort(403)

    payroll = db.get_or_404(Payroll, payroll_id)
    if payroll.payment_date is None:
        abort(409, description="Only paid payroll records can be corrected here.")
    employees = Employee.query.order_by(Employee.last_name).all()

    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        period_start = read_date(request.form.get("pay_period_start"))
        period_end = read_date(request.form.get("pay_period_end"))
        payment_date = read_date(request.form.get("payment_date", "").strip())
        basic_salary = read_money(request.form.get("basic_salary"))
        allowances = read_money(request.form.get("allowances"), Decimal("0.00"))
        deductions = read_money(request.form.get("deductions"), Decimal("0.00"))
        reason = request.form.get("reason", "").strip()
        employee = db.session.get(Employee, employee_id) if employee_id else None

        if employee is None:
            flash("Please select a valid employee.", "error")
        elif not period_start or not period_end or not payment_date:
            flash("Enter valid pay period and payment dates.", "error")
        elif period_end < period_start:
            flash("Pay period end cannot be before its start.", "error")
        elif has_duplicate_payroll(
            employee.id, period_start, period_end, exclude_id=payroll.id
        ):
            flash("A payroll record already exists for this employee and pay period.", "error")
        elif basic_salary is None or allowances is None or deductions is None:
            flash("Enter valid payroll amounts with at most two decimals.", "error")
        elif deductions > basic_salary + allowances:
            flash("Deductions cannot exceed salary plus allowances.", "error")
        elif basic_salary + allowances > MAX_PAYROLL_AMOUNT:
            flash("Salary plus allowances exceeds the supported amount.", "error")
        elif not 10 <= len(reason) <= 1000:
            flash("Enter a correction reason between 10 and 1000 characters.", "error")
        else:
            breakdown_schema_available = attendance_deduction_schema_available()
            before_values = payroll_snapshot(
                payroll, include_breakdown=breakdown_schema_available
            )
            preserve_breakdown = (
                breakdown_schema_available
                and employee.id == payroll.employee_id
                and period_start == payroll.pay_period_start
                and period_end == payroll.pay_period_end
                and basic_salary == payroll.basic_salary
                and deductions == payroll.deductions
            )
            after_values = {
                "employee_id": employee.id,
                "pay_period_start": period_start.isoformat(),
                "pay_period_end": period_end.isoformat(),
                "basic_salary": str(basic_salary),
                "allowances": str(allowances),
                "deductions": str(deductions),
                "net_pay": str(basic_salary + allowances - deductions),
                "payment_date": payment_date.isoformat(),
                "absence_days": (
                    payroll.absence_days if preserve_breakdown else None
                ),
                "late_minutes": (
                    payroll.late_minutes if preserve_breakdown else None
                ),
                "absence_deduction": (
                    str(payroll.absence_deduction)
                    if preserve_breakdown
                    and payroll.absence_deduction is not None
                    else None
                ),
                "late_deduction": (
                    str(payroll.late_deduction)
                    if preserve_breakdown
                    and payroll.late_deduction is not None
                    else None
                ),
            }

            if before_values == after_values:
                flash("Change at least one payroll value before submitting.", "error")
            else:
                statement = update(Payroll).where(
                    Payroll.id == payroll.id,
                    Payroll.payment_date == payroll.payment_date,
                    Payroll.employee_id == payroll.employee_id,
                    Payroll.pay_period_start == payroll.pay_period_start,
                    Payroll.pay_period_end == payroll.pay_period_end,
                    Payroll.basic_salary == payroll.basic_salary,
                    Payroll.allowances == payroll.allowances,
                    Payroll.deductions == payroll.deductions,
                    Payroll.net_pay == payroll.net_pay,
                )
                correction_values = {
                    "employee_id": employee.id,
                    "pay_period_start": period_start,
                    "pay_period_end": period_end,
                    "basic_salary": basic_salary,
                    "allowances": allowances,
                    "deductions": deductions,
                    "net_pay": basic_salary + allowances - deductions,
                    "payment_date": payment_date,
                }
                if breakdown_schema_available:
                    statement = statement.where(
                        Payroll.absence_days == payroll.absence_days,
                        Payroll.late_minutes == payroll.late_minutes,
                        Payroll.absence_deduction == payroll.absence_deduction,
                        Payroll.late_deduction == payroll.late_deduction,
                    )
                    correction_values.update(
                        absence_days=(
                            payroll.absence_days if preserve_breakdown else None
                        ),
                        late_minutes=(
                            payroll.late_minutes if preserve_breakdown else None
                        ),
                        absence_deduction=(
                            payroll.absence_deduction
                            if preserve_breakdown
                            else None
                        ),
                        late_deduction=(
                            payroll.late_deduction if preserve_breakdown else None
                        ),
                    )
                result = db.session.execute(
                    statement.values(**correction_values)
                )
                if result.rowcount != 1:
                    db.session.rollback()
                    abort(
                        409,
                        description=(
                            "This payroll record changed. Reload before correcting it."
                        ),
                    )
                db.session.add(
                    RecordAudit(
                        record_type="payroll",
                        record_id=payroll.id,
                        action="corrected",
                        reason=reason,
                        before_values=before_values,
                        after_values=after_values,
                        actor_id=current_user.id,
                        actor_username=current_user.username,
                    )
                )
                db.session.commit()
                flash("Paid payroll correction recorded successfully.", "success")
                return redirect(
                    url_for("payroll.payroll_detail", payroll_id=payroll.id)
                )

    return render_template(
        "payroll/correct.html",
        payroll=payroll,
        employees=employees,
    )
