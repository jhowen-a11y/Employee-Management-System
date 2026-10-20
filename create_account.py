
from werkzeug.security import generate_password_hash
from app import create_app
from models import db
from models.user import User

app = create_app()

with app.app_context():
    username = "wess"
    email = "wess@example.com"
    password = "12345"
    role = "admin"

    existing_user = User.query.filter_by(username=username).first()

    if existing_user:
        print("Username already exists.")
    else:
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            role=role
        )

        db.session.add(user)
        db.session.commit()

        print("Account created successfully!")
        print(f"Username: {username}")
        print(f"Email: {email}")
        print(f"Role: {role}")
