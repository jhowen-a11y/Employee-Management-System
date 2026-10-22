from datetime import date
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, update
from sqlalchemy.orm import joinedload

from models import db
from models.travel_order import TravelOrder
from models.user import User
from routes.employee_access import current_employee, management_required


travel_order_bp = Blueprint(
    "travel_order",
    __name__,
    url_prefix="/travel-orders",
)
MAX_DESTINATION_LENGTH = 200
MAX_PURPOSE_LENGTH = 5000


def employee_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user.role != User.EMPLOYEE:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@travel_order_bp.route("/")
@employee_required
def my_travel_orders():
    employee = current_employee()
    orders = (
        TravelOrder.query.filter_by(employee_id=employee.id)
        .order_by(TravelOrder.created_at.desc(), TravelOrder.id.desc())
        .all()
        if employee
        else []
    )
    return render_template("travel_orders/list.html", travel_orders=orders)


@travel_order_bp.route("/submit", methods=["GET", "POST"])
@employee_required
def submit_travel_order():
    employee = current_employee()
    if request.method == "POST":
        destination = request.form.get("destination", "").strip()
        purpose = request.form.get("purpose", "").strip()
        departure_date = parse_date(
            request.form.get("departure_date", "").strip()
        )
        return_date = parse_date(request.form.get("return_date", "").strip())

        if not destination or not purpose:
            flash("Destination and purpose are required.", "error")
        elif len(destination) > MAX_DESTINATION_LENGTH:
            flash(
                f"Destination must be {MAX_DESTINATION_LENGTH} characters or fewer.",
                "error",
            )
        elif len(purpose) > MAX_PURPOSE_LENGTH:
            flash(
                f"Purpose must be {MAX_PURPOSE_LENGTH} characters or fewer.",
                "error",
            )
        elif departure_date is None or return_date is None:
            flash("Enter valid departure and return dates.", "error")
        elif return_date < departure_date:
            flash("Return date cannot be earlier than departure date.", "error")
        elif employee is None:
            flash(
                "Your account is not linked to an employee record. Contact HR.",
                "error",
            )
        else:
            travel_order = TravelOrder(
                employee_id=employee.id,
                destination=destination,
                purpose=purpose,
                departure_date=departure_date,
                return_date=return_date,
            )
            db.session.add(travel_order)
            db.session.commit()
            flash("Travel order submitted for approval.", "success")
            return redirect(url_for("travel_order.my_travel_orders"))

    return render_template(
        "travel_orders/submit.html",
        max_destination_length=MAX_DESTINATION_LENGTH,
        max_purpose_length=MAX_PURPOSE_LENGTH,
    )


@travel_order_bp.route("/manage")
@management_required
def manage_travel_orders():
    status = request.args.get("status", "").strip()
    if status and status not in TravelOrder.STATUSES:
        abort(400, description="Select a valid travel order status.")

    query = TravelOrder.query.options(
        joinedload(TravelOrder.employee),
        joinedload(TravelOrder.reviewer),
    )
    if status:
        query = query.filter_by(status=status)
    travel_orders = query.order_by(
        TravelOrder.created_at.desc(),
        TravelOrder.id.desc(),
    ).all()
    return render_template(
        "travel_orders/manage.html",
        travel_orders=travel_orders,
        statuses=TravelOrder.STATUSES,
        selected_status=status,
    )


@travel_order_bp.route("/manage/<int:travel_order_id>/status", methods=["POST"])
@management_required
def update_travel_order_status(travel_order_id):
    new_status = request.form.get("status", "").strip()
    if new_status not in (TravelOrder.APPROVED, TravelOrder.DECLINED):
        abort(400, description="Select Approved or Declined.")

    result = db.session.execute(
        update(TravelOrder)
        .where(
            TravelOrder.id == travel_order_id,
            TravelOrder.status == TravelOrder.PENDING,
        )
        .values(
            status=new_status,
            approved_by=current_user.id,
            approval_date=func.now(),
        )
    )
    if result.rowcount != 1:
        db.session.rollback()
        travel_order = db.session.get(TravelOrder, travel_order_id)
        if travel_order is None:
            abort(404)
        abort(409, description="Only pending travel orders can be reviewed.")

    db.session.commit()
    flash(f"Travel order {new_status.lower()}.", "success")
    return redirect(url_for("travel_order.manage_travel_orders"))
