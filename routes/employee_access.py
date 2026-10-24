from functools import wraps

from flask import abort
from flask_login import current_user

from models import db
from models.attendance import Attendance
from models.leave import Leave
from models.payslip_request import PayslipRequest
from models.travel_order import TravelOrder
from models.user import User


def delete_employee_account(employee):
    # Remove dependent records before deleting the linked employee account.
    Attendance.query.filter_by(employee_id=employee.id).delete(
        synchronize_session=False
    )
    Leave.query.filter_by(employee_id=employee.id).delete(
        synchronize_session=False
    )
    PayslipRequest.query.filter_by(employee_id=employee.id).delete(
        synchronize_session=False
    )
    TravelOrder.query.filter_by(employee_id=employee.id).delete(
        synchronize_session=False
    )
    user = employee.user
    db.session.delete(employee)
    db.session.delete(user)


def current_employee():
    # Find the employee record linked to the signed-in user.
    return current_user.employee


def employee_scoped_query(query, employee_id_column):
    # Limit employee users' queries to their own employee record.
    if current_user.role == User.EMPLOYEE:
        employee = current_employee()
        if employee is None:
            return query.filter(employee_id_column.is_(None))
        query = query.filter(employee_id_column == employee.id)
    return query


def management_required(view):
    # Restrict a view to administrators and HR users.
    @wraps(view)
    def wrapped(*args, **kwargs):
        # Reject users without a management role before running the view.
        if current_user.role not in (User.ADMIN, User.HR):
            abort(403)
        return view(*args, **kwargs)

    return wrapped
