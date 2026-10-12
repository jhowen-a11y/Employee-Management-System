from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# tas import mo dito models and shi
# from .employee import Employee
from .user import User
from .department import Department
from .leave import Leave
from .payroll import Payroll
from .employee import Employee
from .attendance import Attendance