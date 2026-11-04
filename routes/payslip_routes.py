from io import BytesIO
from functools import wraps
from datetime import date

from flask import (
    Blueprint,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from models import db
from models.payroll import Payroll
from models.payslip_request import PayslipRequest
from models.user import User
from routes.employee_access import current_employee, management_required
from services.payroll_deductions import (
    payroll_deduction_breakdown,
)


payslip_bp = Blueprint("payslip", __name__, url_prefix="/payslips")
MAX_DETAILS_LENGTH = 2000


def read_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def employee_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user.role != User.EMPLOYEE:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def owned_payslip_or_404(payroll_id):
    employee = current_employee()
    if employee is None:
        abort(404)
    return Payroll.query.filter_by(
        id=payroll_id,
        employee_id=employee.id,
    ).filter(
        Payroll.payment_date.is_not(None)
    ).first_or_404()


@payslip_bp.route("/")
@employee_required
def my_payslips():
    employee = current_employee()
    payslips = (
        Payroll.query.filter_by(employee_id=employee.id)
        .filter(Payroll.payment_date.is_not(None))
        .order_by(Payroll.pay_period_start.desc(), Payroll.id.desc())
        .all()
        if employee
        else []
    )
    return render_template(
        "payslips/list.html",
        payslips=payslips,
    )


@payslip_bp.route("/<int:payroll_id>")
@employee_required
def payslip_detail(payroll_id):
    payroll = owned_payslip_or_404(payroll_id)
    employee = current_employee()
    return render_template(
        "payslips/detail.html",
        payroll=payroll,
        employee=employee,
        deduction_breakdown=payroll_deduction_breakdown(payroll),
    )


@payslip_bp.route("/<int:payroll_id>/download")
@employee_required
def download_payslip(payroll_id):
    payroll = owned_payslip_or_404(payroll_id)
    employee = current_employee()
    if employee is None:
        abort(404)

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=f"Payslip {payroll.pay_period_start}",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="PayslipTitle",
            parent=styles["Title"],
            alignment=TA_LEFT,
            textColor=colors.HexColor("#17324d"),
            spaceAfter=18,
        )
    )
    gross_pay = payroll.basic_salary + payroll.allowances
    rows = [
        ["Employee", f"{employee.first_name} {employee.last_name}"],
        ["Employee ID", f"EMP-{employee.id:04d}"],
        ["Pay period", f"{payroll.pay_period_start} to {payroll.pay_period_end}"],
        ["Basic salary", f"{payroll.basic_salary:,.2f}"],
        ["Allowances", f"{payroll.allowances:,.2f}"],
        ["Gross salary", f"{gross_pay:,.2f}"],
    ]
    deduction_breakdown = payroll_deduction_breakdown(payroll)
    if deduction_breakdown:
        rows.extend(
            [
                [
                    "Deduction breakdown",
                    "",
                ],
                [
                    (
                        f"Absences ({deduction_breakdown['absence_days']} "
                        f"{'day' if deduction_breakdown['absence_days'] == 1 else 'days'})"
                    ),
                    f"{deduction_breakdown['absence_deduction']:,.2f}",
                ],
                [
                    (
                        f"Lateness ({deduction_breakdown['late_occurrences']} "
                        f"{'occurrence' if deduction_breakdown['late_occurrences'] == 1 else 'occurrences'}, "
                        f"{deduction_breakdown['late_minutes']} minutes)"
                    ),
                    f"{deduction_breakdown['late_deduction']:,.2f}",
                ],
                ["Total deductions", f"{payroll.deductions:,.2f}"],
            ]
        )
    else:
        rows.append(["Deductions", f"{payroll.deductions:,.2f}"])
    rows.extend(
        [
            ["Net salary", f"{payroll.net_pay:,.2f}"],
            ["Payment status", f"Paid on {payroll.payment_date}"],
        ]
    )
    table = Table(rows, colWidths=[2.0 * inch, 4.7 * inch], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf2f7")),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#17324d")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d5dde5")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    document.build(
        [
            Paragraph("Employee Payslip", styles["PayslipTitle"]),
            Paragraph(
                "This payslip reflects the finalized payroll record.",
                styles["BodyText"],
            ),
            Spacer(1, 16),
            table,
        ]
    )
    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="payslip-{payroll.pay_period_start}.pdf"'
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@payslip_bp.route("/requests", methods=["GET", "POST"])
@employee_required
def my_payslip_requests():
    employee = current_employee()
    requests_query = (
        PayslipRequest.query.filter_by(employee_id=employee.id)
        .options(joinedload(PayslipRequest.payroll))
        .order_by(PayslipRequest.request_date.desc(), PayslipRequest.id.desc())
        if employee
        else None
    )

    if request.method == "POST":
        if employee is None:
            abort(403)
        period_start = read_date(
            request.form.get("pay_period_start", "").strip()
        )
        period_end = read_date(request.form.get("pay_period_end", "").strip())
        reason = request.form.get("reason", "").strip()
        details = request.form.get("details", "").strip()

        if not period_start or not period_end:
            flash("Enter a valid pay period start and end date.", "error")
        elif period_end < period_start:
            flash("Pay period end cannot be before its start.", "error")
        elif reason not in PayslipRequest.REASONS:
            flash("Select a valid reason for your request.", "error")
        elif len(details) > MAX_DETAILS_LENGTH:
            flash(
                f"Additional details must be {MAX_DETAILS_LENGTH} characters or fewer.",
                "error",
            )
        else:
            payroll = Payroll.query.filter_by(
                employee_id=employee.id,
                pay_period_start=period_start,
                pay_period_end=period_end,
            ).first()

        valid_request = (
            period_start is not None
            and period_end is not None
            and period_end >= period_start
            and reason in PayslipRequest.REASONS
            and len(details) <= MAX_DETAILS_LENGTH
        )
        if valid_request and payroll is not None and payroll.payment_date:
            flash(
                "This payslip is already available in My Payslips.",
                "success",
            )
            return redirect(
                url_for("payslip.payslip_detail", payroll_id=payroll.id)
            )
        elif valid_request and PayslipRequest.query.filter_by(
            employee_id=employee.id,
            pay_period_start=period_start,
            pay_period_end=period_end,
            status=PayslipRequest.PENDING,
        ).first():
            flash("A pending request already exists for this pay period.", "error")
        elif valid_request:
            payslip_request = PayslipRequest(
                employee_id=employee.id,
                payroll_id=payroll.id if payroll else None,
                pay_period_start=period_start,
                pay_period_end=period_end,
                reason=reason,
                details=details or None,
            )
            db.session.add(payslip_request)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                duplicate_exists = PayslipRequest.query.filter_by(
                    employee_id=employee.id,
                    pay_period_start=period_start,
                    pay_period_end=period_end,
                    status=PayslipRequest.PENDING,
                ).first()
                if duplicate_exists is None:
                    raise
                flash(
                    "A pending request already exists for this pay period.",
                    "error",
                )
            else:
                flash("Payslip request submitted successfully.", "success")
                return redirect(url_for("payslip.my_payslip_requests"))

    request_history = requests_query.all() if requests_query is not None else []
    return render_template(
        "payslips/requests.html",
        request_history=request_history,
        reasons=PayslipRequest.REASONS,
        max_details_length=MAX_DETAILS_LENGTH,
    )


@payslip_bp.route("/manage")
@management_required
def manage_payslip_requests():
    status = request.args.get("status", "").strip()
    if status and status not in PayslipRequest.STATUSES:
        abort(400, description="Select a valid request status.")

    requests_query = PayslipRequest.query.options(
        joinedload(PayslipRequest.employee),
        joinedload(PayslipRequest.payroll),
        joinedload(PayslipRequest.reviewer),
    )
    if status:
        requests_query = requests_query.filter_by(status=status)
    requests_list = requests_query.order_by(
        PayslipRequest.request_date.desc(),
        PayslipRequest.id.desc(),
    ).all()
    return render_template(
        "payslips/manage_requests.html",
        payslip_requests=requests_list,
        selected_status=status,
        statuses=PayslipRequest.STATUSES,
    )


@payslip_bp.route("/manage/<int:request_id>", methods=["GET", "POST"])
@management_required
def review_payslip_request(request_id):
    payslip_request = db.session.get(PayslipRequest, request_id)
    if payslip_request is None:
        abort(404)

    if request.method == "POST":
        new_status = request.form.get("status", "").strip()
        remarks = request.form.get("hr_remarks", "").strip()
        if new_status not in (PayslipRequest.APPROVED, PayslipRequest.REJECTED):
            abort(400, description="Select Approved or Rejected.")
        if len(remarks) > MAX_DETAILS_LENGTH:
            abort(
                400,
                description=(
                    f"HR remarks must be {MAX_DETAILS_LENGTH} characters or fewer."
                ),
            )
        if payslip_request.status != PayslipRequest.PENDING:
            abort(409, description="This request has already been reviewed.")
        matching_payroll = payslip_request.payroll
        if matching_payroll is None:
            matching_payroll = Payroll.query.filter_by(
                employee_id=payslip_request.employee_id,
                pay_period_start=payslip_request.pay_period_start,
                pay_period_end=payslip_request.pay_period_end,
            ).first()
        if (
            new_status == PayslipRequest.APPROVED
            and (
                matching_payroll is None
                or matching_payroll.payment_date is None
            )
        ):
            flash(
                "Create and finalize payroll for this period before approving the request.",
                "error",
            )
            return redirect(
                url_for(
                    "payslip.review_payslip_request",
                    request_id=payslip_request.id,
                )
            )

        result = db.session.execute(
            update(PayslipRequest)
            .where(
                PayslipRequest.id == payslip_request.id,
                PayslipRequest.status == PayslipRequest.PENDING,
            )
            .values(
                status=new_status,
                payroll_id=matching_payroll.id if matching_payroll else None,
                hr_remarks=remarks or None,
                reviewed_by=current_user.id,
                reviewed_at=func.now(),
            )
        )
        if result.rowcount != 1:
            db.session.rollback()
            abort(409, description="This request has already been reviewed.")
        db.session.commit()
        flash(f"Payslip request {new_status.lower()}.", "success")
        return redirect(url_for("payslip.manage_payslip_requests"))

    payroll_record = payslip_request.payroll
    if payroll_record is None:
        payroll_record = Payroll.query.filter_by(
            employee_id=payslip_request.employee_id,
            pay_period_start=payslip_request.pay_period_start,
            pay_period_end=payslip_request.pay_period_end,
        ).first()
    return render_template(
        "payslips/review_request.html",
        payslip_request=payslip_request,
        payroll_record=payroll_record,
    )
