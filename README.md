# Employee Management System

A role-based employee management web application built with Flask and PostgreSQL. Manage employee records, departments, attendance, leave requests, and payroll from one place.

## Contents

- [Features](#features)
- [Technology](#technology)
- [Getting started](#getting-started)
- [Database setup](#database-setup)
- [Create the first administrator](#create-the-first-administrator)
- [Run the application](#run-the-application)
- [Roles and access](#roles-and-access)
- [Main pages](#main-pages)
- [Run tests](#run-tests)
- [Production notes](#production-notes)
- [Project structure](#project-structure)

## Features

- Employee profiles and department management
- Attendance records and leave-request review
- Payroll management for HR/admins and finalized payslips for employees
- Server-side search, sorting, filtering, and pagination across management lists
- Employee payslip requests with HR/admin approval and request history
- Employee travel order requests with HR/admin approval tracking
- Administrator-only PostgreSQL backups and safe restore into a new database
- Separate administrator, HR, and employee experiences
- Sign-in required for application pages, with CSRF protection on forms
- Same-origin page navigation with responsive skeletons and full-page fallback
- PostgreSQL schema migrations for query-performance indexes

## Technology

- Python 3.10+
- Flask, Flask-Login, Flask-SQLAlchemy, and Flask-Migrate
- PostgreSQL with Psycopg 3
- Jinja templates, HTML, CSS, and JavaScript
- Server-rendered page navigation progressively enhanced in the browser

Internal GET links load fresh server-rendered content without reloading the
shared navigation or assets. Slow page responses show layout-matched skeletons;
forms and downloads keep their normal browser behavior. Responses include
`Server-Timing` values for total application processing and Supabase profile
photo URL signing, along with database query time/count, to help identify
remaining production bottlenecks. Signed photo URLs are reused briefly only
for the same account and role.

## Getting started

### Prerequisites

- Python 3.10 or newer
- A running PostgreSQL server and an empty database for a new installation
- Git

### Get the code and install dependencies

Clone the repository and move into the project directory:

```powershell
git clone https://github.com/jhowen-a11y/Employee-Management-System.git
cd Employee-Management-System
```

Create and activate a virtual environment, then install the pinned dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS or Linux, activate the environment with:

```bash
source .venv/bin/activate
```

### Configure environment variables

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
SECRET_KEY=replace_with_a_random_secret
FLASK_DEBUG=0
```

Replace the database placeholders with your PostgreSQL connection details. Generate a strong secret key with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the generated value into `SECRET_KEY`. Use the full connection string provided by your database host, including any required SSL parameters. URL-encode special characters in the database username or password. Do not put spaces around `=` in `.env`.

The app will not start unless both `DATABASE_URL` and `SECRET_KEY` are set. Keep `.env` private; it is excluded from Git.

## Database setup

The migration history starts with a baseline for an **existing schema**. That baseline does not create the core tables. Choose the setup path that matches your database.

### New, empty database

Create the tables from the current SQLAlchemy models once:

```powershell
flask --app app shell
```

At the Python prompt, run:

```python
from models import db
db.create_all()
exit()
```

`db.create_all()` also creates the indexes defined by the models. Mark the current migration version as applied so the index migration does not try to create those indexes again:

```powershell
flask --app app db stamp head
```

### Existing database

Back up the database, then apply pending migrations:

```powershell
flask --app app db upgrade
```

The migrations add indexes for attendance, leave, and payroll queries, and a `payslip_requests` table for employee requests. A follow-up migration stores the requested pay period independently so employees can request missing periods that do not yet have a payroll row. Apply pending migrations with the command above. HR must create and finalize payroll through the existing payroll workflow before approving a request; approval never creates or recalculates payroll. A payslip is available only after a payment date has been recorded. Payslips display the saved values on the payroll record rather than recalculating from the employee's current salary. The baseline migration assumes the core tables are already present; it does not migrate records from another database engine. If you are moving data from MySQL or another database, export and migrate that data separately.

> **Note:** Use migrations to change an established database schema. Do not run `db.create_all()` against an existing production database.

## Create the first administrator

There is no public sign-up page. Create the initial administrator interactively:

```powershell
flask --app app create-admin
```

Enter an administrator username, email, and password when prompted. Passwords must be at least 8 characters. After signing in, administrators can manage accounts and roles from **Users & Roles**. Employees should be created through **Add Employee** so each employee account is linked to an employee record.

## Run the application

Start the local development server:

```powershell
python app.py
```

Open <http://127.0.0.1:5000/> in your browser. Press `Ctrl+C` in the terminal to stop the server.

## Roles and access

| Role | Typical access |
| --- | --- |
| **Administrator** | Manage user accounts and roles, employee profiles, departments, attendance, leave, payroll, payslip requests, and travel orders. |
| **HR** | Manage employee employment details and departments, attendance, payroll, payslip requests, travel orders, and leave review. HR cannot manage administrator/HR accounts or employee login credentials. |
| **Employee** | View their own employee details, attendance, leave, finalized payslips, and request histories; submit their own leave, payslip, and travel order requests; update their profile. |

All application pages require sign-in. Users are redirected to a role-specific home page after signing in. Payroll history cannot be deleted.

## Attendance-based payroll deductions

New payroll records calculate absence and late deductions on the server. The add-payroll preview is informational; saving recalculates from the current attendance and approved-leave records. Absences are charged only for explicit `Absent` entries on Monday–Friday, excluding approved leave and configured non-working dates. Missing attendance is never assumed to be an absence. Late deductions use only records marked `Late` with a time-in; one maximum late duration is used per date to avoid duplicate daily charges. Existing payroll records keep their saved totals and are not backfilled.

The current project has no employee-specific schedule or holiday calendar. The default schedule is 22 working days per month, 8 hours per day, an 08:00 start, and no grace period. Configure these server-side environment variables when the organization’s schedule differs:

| Variable | Default | Purpose |
| --- | --- | --- |
| `EMS_PAYROLL_MONTHLY_WORKING_DAYS` | `22` | Monthly denominator for the daily rate |
| `EMS_PAYROLL_HOURS_PER_DAY` | `8` | Hours used to derive hourly rate |
| `EMS_PAYROLL_SHIFT_START` | `08:00` | Start time used to derive minutes late for records already marked `Late` |
| `EMS_PAYROLL_LATE_GRACE_MINUTES` | `0` | Grace minutes subtracted from the recorded lateness |
| `EMS_PAYROLL_NON_WORKING_DATES` | empty | Comma-separated `YYYY-MM-DD` dates excluded from weekday absence/late deductions |

These settings are app-wide, not per employee. Weekends are treated as rest days; this implementation does not model employee-specific rotating shifts or scheduled weekend work. Historical payrolls whose breakdown fields are empty continue to display their original total deduction without inventing absence/late amounts. The payroll migration adds nullable breakdown columns and prevents duplicate employee/pay-period records; if duplicate periods already exist, the migration stops without deleting or changing payroll rows so they can be reviewed first.

## Main pages

| Page | URL | Access |
| --- | --- | --- |
| Sign in | `/login` | Public |
| Admin dashboard | `/` | Administrator |
| Employee portal | `/employee/home` | Employee |
| HR dashboard | `/hr/home` | HR |
| Employees | `/employees/` | Role-dependent |
| Departments | `/departments/` | Administrator and HR |
| Attendance | `/attendance/` | Role-dependent |
| Leave requests | `/leaves/` | Role-dependent |
| Payroll Management | `/payroll/` | Administrator and HR |
| My Payslips | `/payslips/` | Employee |
| Payslip Requests | `/payslips/requests` | Employee |
| Manage Payslip Requests | `/payslips/manage` | Administrator and HR |
| My Travel Orders | `/travel-orders/` | Employee |
| Submit Travel Order | `/travel-orders/submit` | Employee |
| Manage Travel Orders | `/travel-orders/manage` | Administrator and HR |
| Users & Roles | `/users/` | Administrator |
| Database Backup | `/admin/database-backups` | Administrator |
| Edit profile | `/users/profile` | Signed-in users |
| Users API | `/users/api` | Administrator |

## Run tests

### Selective recovery staging (Phase 1)

Selective recovery is separate from full restore. Phase 1 provides configuration
and target guards only; it does not yet create staging databases, restore backups,
preview records, or insert recovered records.

Configure `RECOVERY_STAGING_DATABASE_URL` privately with the SQLAlchemy driver
`postgresql+psycopg`, a dedicated local staging role, an explicit loopback host
(`127.0.0.1`, `::1`, or `localhost`), a port, and maintenance database `postgres`.
Do not change `DATABASE_URL` or the Supabase Storage settings. Do not reuse active
database credentials. An absent setting disables staging validation without
interrupting normal EMS or existing backups.

The guards reject remote hosts, URL query options, unsafe database names, an
overlapping active local server, and inherited `PGHOSTADDR`, `PGSERVICE`,
`PGSERVICEFILE`, or `PGOPTIONS` overrides. Disposable target names are generated
by the server. A generated name is **not** proof of ownership: later lifecycle
code must record successful creation and require that record before cleanup.

Before Phase 2, verify the dedicated local role can connect to `postgres` and
has `CREATEDB` permission using a read-only role query. A running service or open
TCP port alone does not verify authentication or restore compatibility. No
migration is required for Phase 1.

Run the guard tests with:

```powershell
python -m unittest discover -s tests -p test_record_recovery.py -v
```

Run the test suite from the project root:

```powershell
python -m unittest discover -s tests -v
```

## Production notes

- Set `DATABASE_URL` and a strong `SECRET_KEY` in your hosting provider's environment settings. Do not rely on a local `.env` file in production.
- Database backups require PostgreSQL `pg_dump` and `pg_restore` binaries on the application server, network access to the database, and a database account with permission to create a separate database to restore into. Signed `.emsbackup` packages and their history are stored in the private Supabase Storage bucket named by `SUPABASE_BACKUP_BUCKET` (default: `database-backups`); the application server uses temporary staging files only while creating or restoring a backup. Configure `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (or `SUPABASE_SECRET_KEY`) and create a private bucket before using backups. Set `PG_DUMP_PATH` and `PG_RESTORE_PATH` if the PostgreSQL utilities are not on `PATH`. Backups are limited to 512 MB. Restore validates the signed package before creating a new database; it never replaces the active database. Keep `SECRET_KEY` stable because packages are signed with it. Password-encrypted backups use AES-256-GCM and require the password to restore. Database backups do not include profile pictures stored separately in Supabase Storage.
- The application disables Flask debug mode so browser requests do not expose the interactive debugger or tracebacks. Use a production WSGI server when deploying; do not enable Flask's development server in production.
- Back up the database before applying migrations.
- If deploying on Vercel, configure the environment variables for each deployment environment and redeploy after changing them.
- Profile-picture uploads use Supabase Storage so they persist across Vercel deployments. Photos appear in the shared navigation, employee directory, and employee-related pages. Create a bucket named `employee-profiles` (or set `SUPABASE_PROFILE_BUCKET` to another bucket name); private buckets are supported using expiring signed URLs. Configure `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in Vercel. A Supabase secret key can be used as `SUPABASE_SECRET_KEY` instead. Keep either key server-side; never expose it in browser code. Existing local pictures continue to use their local static files until replaced.

## Project structure

```text
.
├── app.py                 # Flask app setup, authentication checks, and CLI commands
├── models/                # SQLAlchemy models
├── routes/                # Feature blueprints and access-control helpers
├── services/              # Business services, including backup and payroll calculations
├── templates/             # Jinja pages, organized by feature
├── static/                # CSS and JavaScript
├── migrations/            # Alembic/Flask-Migrate schema history
├── tests/                 # Unit and schema tests
├── requirements.txt       # Python dependencies
└── .gitignore
```
