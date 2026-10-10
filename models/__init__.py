from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# tas import mo dito models and shi
# from .employee import Employee
from .user import User
# from .dep
# from .atte