from flask import Blueprint
from models import db
from models.user import User

user_bp = Blueprint('user_bp', __name__)

@user_bp.route('/', methods=['GET'])
def get_all_users():
    stmt = db.select(User)
    users = db.session.execute(stmt).scalars().all()

    user_list = []
    for user in users:
        user_list.append({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role
        })

    return {"users": user_list}, 200
