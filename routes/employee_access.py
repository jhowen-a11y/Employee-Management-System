from functools import wraps

from flask import abort
from flask_login import current_user

from models import db
from models.attendance import Attendance
from models.leave import Leave
from models.payslip_request import PayslipRequest
from models.record_audit import RecordAudit
from models.travel_order import TravelOrder
from models.user import User


def delete_employee_account(employee):
    # Remove dependent records before deleting the linked employee account.
    attendance_records = Attendance.query.filter_by(
        employee_id=employee.id
    ).all()
    for record in attendance_records:
        db.session.add(
            RecordAudit(
                record_type="attendance",
                record_id=record.id,
                action="deleted",
                reason="Attendance archived as part of employee account deletion.",
                before_values={
                    "employee_id": record.employee_id,
                    "attendance_date": record.attendance_date.isoformat(),
                    "time_in": (
                        record.time_in.isoformat() if record.time_in else None
                    ),
                    "time_out": (
                        record.time_out.isoformat() if record.time_out else None
                    ),
                    "status": record.status,
                },
                after_values={"deleted": True},
                actor_id=current_user.id,
                actor_username=current_user.username,
            )
        )
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
