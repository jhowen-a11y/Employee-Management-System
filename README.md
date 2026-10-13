# Employee Management System

A Flask application for managing employee records, departments, attendance, leave requests, and payroll. It uses Flask-SQLAlchemy with a MySQL database and Jinja templates.

## Tech stack

- Python 3
- Flask
- Flask-SQLAlchemy and SQLAlchemy
- MySQL with the PyMySQL driver
- Jinja templates
- python-dotenv

## Project structure

```text
.
├── app.py                  # Flask application factory and entry point
├── init_db.py              # Creates database tables
├── requirements.txt        # Python dependencies
├── models/                 # SQLAlchemy models and relationships
├── routes/                 # Flask blueprints for application features
├── static/                 # CSS and JavaScript assets
└── templates/              # Jinja templates grouped by feature
```

## Setup

### Prerequisites

- Python 3.10 or newer
- MySQL Server

### Install dependencies

Create and activate a virtual environment, then install the project dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install PyMySQL
```

The app uses PyMySQL in its MySQL connection URL. Install it if it is not already included in your environment.

### Configure MySQL

Create a database, for example:

```sql
CREATE DATABASE employee_management;
```

Create a `.env` file in the project root with credentials for that database:

```env
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_HOST=localhost
DB_PORT=3306
DB_NAME=employee_management
SECRET_KEY=replace_with_a_random_secret
FLASK_DEBUG=1
```

`app.py` builds the SQLAlchemy connection URL from the `DB_*` variables. Set `SECRET_KEY` to a long, random value and keep `.env` private; do not commit real credentials. If it is omitted, the app generates a temporary key, so session data will not survive a restart.

### Create tables and run

Create the database tables:

```powershell
python init_db.py
```

Start the development server:

```powershell
python app.py
```

The app is served at <http://127.0.0.1:5000/>.

## Features and routes

| Feature | URL prefix | Description |
| --- | --- | --- |
| Employees | `/employees` | List and view employee records |
| Departments | `/departments` | List, view, add, edit, and delete departments |
| Attendance | `/attendance` | List, view, add, edit, and delete attendance records |
| Leave | `/leaves` | List, view, submit, update status, and delete leave requests |
| Payroll | `/payroll` | List, view, add, edit, and delete payroll records |

Employee, department, attendance, leave, and payroll models are defined in `models/` and connected through SQLAlchemy relationships. A `User` model is also present and linked to employees; user authentication is not currently implemented, and the application routes do not require sign-in. Do not expose this app to untrusted networks without adding appropriate authentication and authorization.
