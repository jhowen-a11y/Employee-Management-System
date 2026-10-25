from datetime import date
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import String, cast, func, or_, update
from sqlalchemy.orm import joinedload

from models import db
from models.employee import Employee
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
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    date_from_value = request.args.get("from", "").strip()
    date_to_value = request.args.get("to", "").strip()
    date_from = parse_date(date_from_value) if date_from_value else None
    date_to = parse_date(date_to_value) if date_to_value else None
    if (date_from_value and date_from is None) or (date_to_value and date_to is None):
        abort(400, description="Enter valid departure date filters.")
    if status and status not in TravelOrder.STATUSES:
        abort(400, description="Select a valid travel order status.")
    sort = request.args.get("sort", "departure").strip()
    direction = request.args.get("direction", "desc").strip().lower()
    sort_fields = {
        "destination": (TravelOrder.destination,),
        "departure": (TravelOrder.departure_date,),
        "return": (TravelOrder.return_date,),
        "submission": (TravelOrder.created_at,),
        "status": (TravelOrder.status,),
    }
    if sort not in sort_fields:
        sort = "departure"
    if direction not in {"asc", "desc"}:
        direction = "desc"
    sort_expressions = [
        expression.asc() if direction == "asc" else expression.desc()
        for expression in sort_fields[sort]
    ]
    query = TravelOrder.query.join(TravelOrder.employee)
    if employee:
        query = query.filter(TravelOrder.employee_id == employee.id)
    else:
        query = query.filter(TravelOrder.employee_id == -1)
    if search:
        search_pattern = f"%{search}%"
        search_filters = [
            TravelOrder.destination.ilike(search_pattern),
            TravelOrder.purpose.ilike(search_pattern),
        ]
        if employee:
            search_filters.extend([
                Employee.first_name.ilike(search_pattern),
                Employee.last_name.ilike(search_pattern),
                (Employee.first_name + " " + Employee.last_name).ilike(search_pattern),
            ])
        if search.isdecimal():
            search_filters.append(
                cast(TravelOrder.employee_id, String).ilike(search_pattern)
            )
        query = query.filter(or_(*search_filters))
    if status:
        query = query.filter(TravelOrder.status == status)
    if date_from:
        query = query.filter(TravelOrder.departure_date >= date_from)
    if date_to:
        query = query.filter(TravelOrder.departure_date <= date_to)
    orders = query.order_by(
        *sort_expressions, TravelOrder.id.desc()
    ).paginate(
        page=request.args.get("page", 1, type=int),
        per_page=50,
        error_out=False,
    )
    return render_template(
        "travel_orders/list.html",
        travel_orders=orders,
        search=search,
        status=status,
        statuses=TravelOrder.STATUSES,
        date_from=date_from_value,
        date_to=date_to_value,
        sort=sort,
        direction=direction,
    )


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

    search = request.args.get("q", "").strip()
    date_from_value = request.args.get("from", "").strip()
    date_to_value = request.args.get("to", "").strip()
    date_from = parse_date(date_from_value) if date_from_value else None
    date_to = parse_date(date_to_value) if date_to_value else None
    if (date_from_value and date_from is None) or (date_to_value and date_to is None):
        abort(400, description="Enter valid departure date filters.")
    sort = request.args.get("sort", "submission").strip()
    direction = request.args.get("direction", "desc").strip().lower()
    sort_fields = {
        "employee": (Employee.last_name, Employee.first_name),
        "destination": (TravelOrder.destination,),
        "departure": (TravelOrder.departure_date,),
        "return": (TravelOrder.return_date,),
        "submission": (TravelOrder.created_at,),
        "status": (TravelOrder.status,),
    }
    if sort not in sort_fields:
        sort = "submission"
    if direction not in {"asc", "desc"}:
        direction = "desc"
    sort_expressions = [
        expression.asc() if direction == "asc" else expression.desc()
        for expression in sort_fields[sort]
    ]

    query = TravelOrder.query.join(TravelOrder.employee).options(
        joinedload(TravelOrder.employee),
        joinedload(TravelOrder.reviewer),
    )
    if search:
        search_pattern = f"%{search}%"
        search_filters = [
            Employee.first_name.ilike(search_pattern),
            Employee.last_name.ilike(search_pattern),
            (Employee.first_name + " " + Employee.last_name).ilike(search_pattern),
            TravelOrder.destination.ilike(search_pattern),
            TravelOrder.purpose.ilike(search_pattern),
        ]
        if search.isdecimal():
            search_filters.extend([
                cast(Employee.id, String).ilike(search_pattern),
                cast(TravelOrder.id, String).ilike(search_pattern),
            ])
        query = query.filter(or_(*search_filters))
    if status:
        query = query.filter(TravelOrder.status == status)
    if date_from:
        query = query.filter(TravelOrder.departure_date >= date_from)
    if date_to:
        query = query.filter(TravelOrder.departure_date <= date_to)
    travel_orders = query.order_by(
        *sort_expressions, TravelOrder.id.desc()
    ).paginate(
        page=request.args.get("page", 1, type=int),
        per_page=50,
        error_out=False,
    )
    return render_template(
        "travel_orders/manage.html",
        travel_orders=travel_orders,
        statuses=TravelOrder.STATUSES,
        selected_status=status,
        search=search,
        date_from=date_from_value,
        date_to=date_to_value,
        sort=sort,
        direction=direction,
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
