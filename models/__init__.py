from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
migrate = Migrate()

# tas import mo dito models and shi
# from .employee import Employee
from .user import User
from .department import Department
from .leave import Leave
from .payroll import Payroll
from .payslip_request import PayslipRequest
from .travel_order import TravelOrder
from .employee import Employee
from .attendance import Attendance
from .record_audit import RecordAudit
