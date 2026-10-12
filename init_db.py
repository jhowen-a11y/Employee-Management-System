from app import create_app
from models import db

app = create_app()

def init_database():
    with app.app_context():
        try:
            db.create_all()
            print("Database tables created successfully")
        except Exception as e:
            print(f"Error creating database tables: {e}")

if __name__ == "__main__":
    init_database()