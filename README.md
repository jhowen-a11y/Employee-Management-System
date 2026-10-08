# Employee Management System

A modular web application built with Python and Flask for managing employees, user authentication, and attendance tracking. 

## 🛠 Tech Stack

*   **Backend:** Python 3.x, Flask
*   **Database:** MySQL (via Flask-SQLAlchemy & PyMySQL)
*   **Frontend:** HTML, CSS, JavaScript (Jinja2 Templates)
*   **Environment Management:** python-dotenv

## 📂 Project Structure

This project follows a modular Flask architecture using Blueprints:

```text
employee_management/
├── app.py                     # Main application entry point and configuration
├── .env                       # Environment variables (Database credentials, keys)
├── requirements.txt           # Python dependencies
├── models/                    # Database models (SQLAlchemy)
│   ├── attendance.py
│   ├── department.py
│   ├── employee.py
│   └── user.py
├── routes/                    # Flask Blueprints (API / View routes)
│   ├── attendance_routes.py
│   ├── employee_routes.py
│   └── user_routes.py
├── static/                    # Static assets
│   ├── css/
│   └── js/
└── templates/                 # HTML templates
    ├── dashboard.html
    ├── employees.html
    └── login.html
```

## 🚀 Getting Started

Follow these steps to set up the project locally for development.

### 1. Prerequisites
*   [Python 3.8+](https://www.python.org/downloads/)
*   [MySQL Server](https://dev.mysql.com/downloads/) running locally or remotely.

### 2. Clone and Setup Environment
Clone the repository and navigate into the project directory:
```bash
git clone <your-repository-url>
cd employee_management
```

Create and activate a virtual environment:
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install Flask Flask-SQLAlchemy pymysql python-dotenv
```
*(Note: Once you have your dependencies finalized, you can freeze them into a `requirements.txt` using `pip freeze > requirements.txt`)*

### 4. Database Configuration
1. Open your MySQL client (e.g., MySQL Workbench, CLI) and create the database:
   ```sql
   CREATE DATABASE employee_management;
   ```
2. Create a `.env` file in the root directory (alongside `app.py`) and add your database credentials:
   ```env
   FLASK_APP=app.py
   FLASK_DEBUG=1
   SECRET_KEY=your-development-secret-key
   
   # MySQL Connection
   DB_USER=root
   DB_PASSWORD=your_mysql_password
   DB_HOST=localhost
   DB_PORT=3306
   DB_NAME=employee_management
   
   SQLALCHEMY_DATABASE_URI=mysql+pymysql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}
   ```

### 5. Run the Application
Start the Flask development server:
```bash
flask run
# OR
python app.py
```
The application will be accessible at `http://127.0.0.1:5000/`.

## 🚧 Development Status
Currently in the initial production phase. Core file structure, database connections, and environment variables are configured. Next steps involve defining the SQLAlchemy models and wiring up the Flask Blueprints.
