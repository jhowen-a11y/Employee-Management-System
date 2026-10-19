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

Create a `.env` file in the project root. Set `DATABASE_URL` to the PostgreSQL
connection string provided by your database host (for Supabase, find it under
**Project Settings > Database** or **Connect**):

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE
SECRET_KEY=replace_with_a_random_secret
FLASK_DEBUG=1
```

Use the complete connection string from your provider, including any required
SSL query parameters. If the password contains URL-reserved characters, use the
URL-encoded password in the connection string. Do not add spaces around `=`.
Keep `.env` private; it is ignored by Git. The app requires both `DATABASE_URL`
and `SECRET_KEY` and will not start if either is missing.

For Vercel, add `DATABASE_URL` and `SECRET_KEY` under **Project Settings >
Environment Variables** for each deployment environment you use, then redeploy.
Vercel does not use your local `.env` file. Keep `FLASK_DEBUG` disabled in
production.

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
the first administrator signs in, they can create administrator and HR
accounts from **Users & Roles**, add employees from **Add Employee**, or
associate an existing account with a department from the **Employees** list.

Start the development server:

```powershell
python app.py
```

The app is served at <http://127.0.0.1:5000/>.

## Features and routes

| Feature | URL prefix | Description |
| --- | --- | --- |
| Employees | `/employees` | List and view records; administrators can add employee accounts, assign existing users to a department, and delete employee accounts when no payroll history exists |
| Departments | `/departments` | List, view, add, edit, and delete departments without assigned employees |
| Attendance | `/attendance` | List, view, add, edit, and delete attendance records |
| Leave | `/leaves` | List, view, submit, update status, and delete leave requests |
| Payroll | `/payroll` | List, view, add, and edit payroll records; payroll history cannot be deleted |
| Users & Roles | `/users` | Admin-only account creation, account editing, role assignment, and account deletion when no payroll history exists; `/users/profile` is available to all signed-in users |
| Employee Home | `/employee/home` | Employee portal with personal record summaries |
| HR Home | `/hr/home` | HR dashboard with management counts and shortcuts |
| Admin Dashboard | `/` | Organization counts and management shortcuts |

All application pages require sign-in. Administrators manage accounts and roles;
only administrators can add or edit employee accounts. Employee users can view
only their own employee information, department, attendance, leave requests, and
payroll; they can submit leave requests for themselves but cannot manage
employee records. HR can manage attendance, departments, leave, and payroll but
cannot create employee accounts or manage users and roles. Administrators can
manage user account details and roles, employee profiles (including salary,
department, position, and names), and payroll. HR and administrators can add
and edit payroll records; payroll history is not deletable. Employee accounts
are created through
**Add Employee** so every employee login is linked to an employee record. All
signed-in users can update their username, email, and password from **Edit
profile**. Every POST form requires a valid CSRF token. Employee users land on
the `/employee/home` portal and HR users land on the `/hr/home` dashboard after
signing in; administrators land on the organization dashboard. The
administrator-only users API is available at `/users/api`.
