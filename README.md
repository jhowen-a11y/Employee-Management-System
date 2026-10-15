# Employee Management System

A Flask application for managing employee records, departments, attendance, leave requests, and payroll. It uses Flask-SQLAlchemy with a PostgreSQL database and Jinja templates.

## Tech stack

- Python 3
- Flask
- Flask-SQLAlchemy and SQLAlchemy
- PostgreSQL with the psycopg driver
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
- PostgreSQL Server

### Install dependencies

Create and activate a virtual environment, then install the project dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Configure PostgreSQL

Create a database, for example:

```sql
CREATE DATABASE employee_management;
```

Create a `.env` file in the project root with credentials for that database:

```env
DB_USER=postgres
DB_PASSWORD=your_postgresql_password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=employee_management
SECRET_KEY=replace_with_a_random_secret
FLASK_DEBUG=1
```

`app.py` builds a psycopg PostgreSQL connection URL from the `DB_*` variables. Set `SECRET_KEY` to a long, random value and keep `.env` private; do not commit real credentials. The app requires this key and will not start if it is missing.

`python init_db.py` creates missing tables in the configured PostgreSQL
database; it does not transfer records from the old MySQL database. Export and
migrate any existing data separately before switching production traffic.

### Create tables and run

Create the database tables:

```powershell
python init_db.py
```

Create the first administrator account from the command line. There is no
public sign-up page:

```powershell
flask --app app create-admin
```

The command prompts for an administrator username, email, and password. After
the first administrator signs in, they can create accounts and assign the
`admin`, `hr`, or `employee` role from **Users & Roles**.

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
| Users & Roles | `/users` | Admin-only account creation and role assignment |
| Employee Home | `/employee/home` | Employee landing page placeholder |
| HR Home | `/hr/home` | HR landing page placeholder |

All application pages require sign-in. Administrators manage accounts and roles;
only administrators can add or edit employee accounts. The existing employee,
HR, and administrator accounts can use the employee-management features.
Employee users land on the `/employee/home` placeholder and HR users land on
the `/hr/home` placeholder after signing in; administrators land on the shared
dashboard. The administrator-only users API is available at `/users/api`.
