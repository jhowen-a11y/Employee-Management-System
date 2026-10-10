import os
from flask import Flask
from dotenv import load_dotenv

# Assuming you will set up Flask-SQLAlchemy in your models directory
from models import db 

# Import the route blueprints from the routes/ folder[cite: 1]
# from routes.employee_routes import employee_bp
# from routes.user_routes import user_bp
# from routes.attendance_routes import attendance_bp

def create_app():
    # Load environment variables from the .env file FIRST
    load_dotenv()

    # Initialize the Flask application
    app = Flask(__name__)

    # Application Configuration using environment variables
    # We provide a fallback string just in case the .env fails to load in development
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback-dev-secret-key')
    
    # MySQL Database Connection 
    # This pulls the MySQL connection string we defined in the .env file
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions (uncomment when you have your db set up in models/)
    #db.init_app(app)

    # Register Blueprints to connect the modular routes/ files to the main app[cite: 1]
    # app.register_blueprint(user_bp, url_prefix='/users')
    # app.register_blueprint(employee_bp, url_prefix='/employees')
    # app.register_blueprint(attendance_bp, url_prefix='/attendance')


    @app.route('/')
    def index():
        # This will eventually render templates/login.html or templates/dashboard.html[cite: 1]
        return "Welcome to the Employee Management System"

    return app

if __name__ == '__main__':
    app = create_app()
    debug_mode = os.environ.get('FLASK_DEBUG') == '1'
    app.run(debug=debug_mode)

# PATI DITO