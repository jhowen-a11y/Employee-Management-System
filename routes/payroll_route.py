
from flask import abort, Blueprint, render_template, request, redirect, url_for, flash
from datetime import date
from decimal import Decimal, InvalidOperation
from flask_login import current_user
from sqlalchemy import String, cast, or_, update
from sqlalchemy.orm import joinedload

from models import db
from models.payroll import Payroll
from models.employee import Employee
from models.record_audit import RecordAudit
from models.user import User
from profile_storage import profile_picture_urls
from routes.employee_access import management_required

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


def payroll_snapshot(payroll):
    return {
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
    )
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
    )


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
        deductions = read_money(request.form.get("deductions"), Decimal("0.00"))

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
        elif basic_salary is None or allowances is None or deductions is None:
            flash("Enter valid payroll amounts with at most two decimals.", "error")
        elif deductions > basic_salary + allowances:
            flash("Deductions cannot exceed salary plus allowances.", "error")
        elif basic_salary + allowances > MAX_PAYROLL_AMOUNT:
            flash("Salary plus allowances exceeds the supported amount.", "error")
        else:
            net_pay = basic_salary + allowances - deductions

            payroll = Payroll(
                employee_id=employee.id,
                pay_period_start=period_start,
                pay_period_end=period_end,
                basic_salary=basic_salary,
                allowances=allowances,
                deductions=deductions,
                net_pay=net_pay,
                payment_date=payment_date
            )

            db.session.add(payroll)
            db.session.commit()

            flash("Payroll record added successfully!", "success")
            return redirect(url_for("payroll.payroll_list"))

        return render_template(
            "payroll/add.html",
            employees=employees
        )

    return render_template(
        "payroll/add.html",
        employees=employees
    )


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

    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        period_start = read_date(request.form.get("pay_period_start"))
        period_end = read_date(request.form.get("pay_period_end"))
        payment_date_value = request.form.get("payment_date", "").strip()
        basic_salary = read_money(request.form.get("basic_salary"))
        allowances = read_money(request.form.get("allowances"), Decimal("0.00"))
        deductions = read_money(request.form.get("deductions"), Decimal("0.00"))
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
        elif basic_salary is None or allowances is None or deductions is None:
            flash("Enter valid payroll amounts with at most two decimals.", "error")
        elif deductions > basic_salary + allowances:
            flash("Deductions cannot exceed salary plus allowances.", "error")
        elif basic_salary + allowances > MAX_PAYROLL_AMOUNT:
            flash("Salary plus allowances exceeds the supported amount.", "error")
        else:
            result = db.session.execute(
                update(Payroll)
                .where(
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
                .values(
                    employee_id=employee.id,
                    pay_period_start=period_start,
                    pay_period_end=period_end,
                    basic_salary=basic_salary,
                    allowances=allowances,
                    deductions=deductions,
                    net_pay=basic_salary + allowances - deductions,
                    payment_date=payment_date,
                )
            )
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
        elif basic_salary is None or allowances is None or deductions is None:
            flash("Enter valid payroll amounts with at most two decimals.", "error")
        elif deductions > basic_salary + allowances:
            flash("Deductions cannot exceed salary plus allowances.", "error")
        elif basic_salary + allowances > MAX_PAYROLL_AMOUNT:
            flash("Salary plus allowances exceeds the supported amount.", "error")
        elif not 10 <= len(reason) <= 1000:
            flash("Enter a correction reason between 10 and 1000 characters.", "error")
        else:
            before_values = payroll_snapshot(payroll)
            after_values = {
                "employee_id": employee.id,
                "pay_period_start": period_start.isoformat(),
                "pay_period_end": period_end.isoformat(),
                "basic_salary": str(basic_salary),
                "allowances": str(allowances),
                "deductions": str(deductions),
                "net_pay": str(basic_salary + allowances - deductions),
                "payment_date": payment_date.isoformat(),
            }

            if before_values == after_values:
                flash("Change at least one payroll value before submitting.", "error")
            else:
                result = db.session.execute(
                    update(Payroll)
                    .where(
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
                    .values(
                        employee_id=employee.id,
                        pay_period_start=period_start,
                        pay_period_end=period_end,
                        basic_salary=basic_salary,
                        allowances=allowances,
                        deductions=deductions,
                        net_pay=basic_salary + allowances - deductions,
                        payment_date=payment_date,
                    )
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
