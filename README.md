# Employee Management System

A full-stack employee management application with a React frontend, a Django REST API, JWT authentication, and PostgreSQL. Managers can maintain employee profiles, employment contracts, attendance, leave, holidays, salaries, payroll, and reports.

## Contents

- [Features](#features)
- [Technology and project structure](#technology-and-project-structure)
- [Prerequisites](#prerequisites)
- [Setup instructions](#setup-instructions)
- [Run locally](#run-locally)
- [Accounts and access](#accounts-and-access)
- [API documentation](#api-documentation)
- [Checks and tests](#checks-and-tests)
- [Technical decisions and assumptions](#technical-decisions-and-assumptions)
- [Troubleshooting](#troubleshooting)
- [Deployment considerations](#deployment-considerations)

## Features

- Create, list, edit, search, and delete employee records, or mark employees inactive to retain employment history.
- Store contact details, profile photos, departments, job titles, reporting managers, and job descriptions.
- Upload contracts and track their start dates, end dates, and status. Read PDFs inside the application with page navigation and zoom.
- Record daily attendance, remote work, absence, and hours worked using forms or the daily roster.
- Record leave requests, approve or reject them, and maintain company holidays.
- Maintain monthly salaries, prepare payroll, record payments, and print or save payslips as PDF.
- View absence, approved leave, missing attendance, expiring contract, working hours, and payroll reports; export record lists and report tables as CSV.
- Use a responsive manager dashboard with loading states and validation/error messages.

## Technology and project structure

| Layer | Implementation |
| --- | --- |
| Frontend | React 19, React Router 7, Vite 8, plain CSS |
| Backend | Django, Django REST Framework, Simple JWT |
| Database | PostgreSQL through Django ORM and migrations |
| Administration | Django admin with Jazzmin |
| Documents | Private local file storage; PDF.js for PDF previews |
| Validation | Backend serializers and model constraints, supplemented by frontend form validation |

```text
employee_management/
├── README.md
├── backend/
│   ├── manage.py
│   ├── .env.example
│   ├── backend/
│   │   ├── settings.py
│   │   ├── test_settings.py
│   │   ├── urls.py
│   │   └── requirements.txt
│   ├── api/
│   │   ├── models.py
│   │   ├── serializers.py
│   │   ├── permissions.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   ├── tests.py
│   │   └── migrations/
│   └── private_media/             # Created when files are uploaded
├── frontend/
│   ├── package.json
│   ├── package-lock.json
│   ├── .env.example
│   ├── vite.config.js
│   ├── scripts/copy-pdf-assets.mjs
│   └── src/
│       ├── App.jsx
│       ├── ManagerDashboard.jsx
│       ├── ContractViewer.jsx
│       ├── managerConfig.js
│       ├── api.js
│       └── pdfEngine.js
└── docs/API.md                    # Links to this API reference
```

Install the frontend dependencies from `frontend/`. The root `package.json` is not the frontend application and does not contain its run scripts.

## Prerequisites

The current project has been checked with Python **3.10.11**, Node.js **22.16.0**, npm **10.9.2**, and PostgreSQL **17.3**. The installed backend uses Django **5.2.17**, Django REST Framework **3.18.1**, and Simple JWT **5.5.1**.

You need:

- Python 3.10 and `pip` to reproduce the checked backend environment.
- Node.js 22.13 or later within the 22.x series, with npm. PDF.js requires at least Node 22.13 in this series.
- A running PostgreSQL installation and access to an administrator role for initial database creation.
- A browser and two terminals for the backend and frontend.

Python dependencies are mostly unpinned in `backend/backend/requirements.txt`, so a fresh installation can resolve different versions. Frontend installations use `package-lock.json` through `npm ci`.

## Setup instructions

The main commands below use **Windows PowerShell** and start from the project root: the directory containing `backend/` and `frontend/`. Existing users should keep their current virtual environment and `.env` files rather than overwrite them.

### 1. Prepare the Python environment

For a new checkout:

```powershell
py -3.10 -m venv env
.\env\Scripts\python.exe -m pip install --upgrade pip
.\env\Scripts\python.exe -m pip install -r .\backend\backend\requirements.txt
```

The commands use the virtual environment's Python directly, so activating PowerShell scripts is unnecessary. If `py` is unavailable, use `python -m venv env` after checking that `python --version` identifies the intended interpreter.

### 2. Set up PostgreSQL

Start the PostgreSQL service. Connect using its administrator account through pgAdmin or `psql`:

```powershell
psql -h 127.0.0.1 -U postgres -d postgres
```

Run the following SQL **once** for a new installation. Replace the example password with your own and use the same password in the next step:

```sql
CREATE USER employee_app WITH PASSWORD 'replace-with-your-local-password';
CREATE DATABASE employee_management OWNER employee_app;
```

The application role owns this database so Django can create and alter its tables during migrations. It does not need PostgreSQL superuser privileges. If you already have an application database and role, use their details instead. Exit `psql` with `\q`.

If `psql` is not on PATH, use its full path from your PostgreSQL installation or run the SQL in pgAdmin's Query Tool connected to the `postgres` database. Execute `CREATE DATABASE` outside a transaction.

### 3. Configure backend environment variables

Copy the example only if `backend/.env` does not already exist:

```powershell
if (-not (Test-Path .\backend\.env)) {
    Copy-Item .\backend\.env.example .\backend\.env
}
```

Edit `backend/.env`:

```dotenv
DB_NAME=employee_management
DB_USER=employee_app
DB_PASSWORD=replace-with-your-local-password
DB_HOST=127.0.0.1
DB_PORT=5432
```

| Variable | Purpose |
| --- | --- |
| `DB_NAME` | PostgreSQL database name |
| `DB_USER` | Application database role |
| `DB_PASSWORD` | Password assigned to that role |
| `DB_HOST` | PostgreSQL host |
| `DB_PORT` | PostgreSQL port; commonly `5432` |

All five values are required. `python-dotenv` loads this file from `backend/`; existing process environment variables take precedence. `backend/.env` is ignored by Git. Never replace its values with another developer's credentials.

### 4. Create the tables and administrator account

From the project root:

```powershell
.\env\Scripts\python.exe .\backend\manage.py migrate
.\env\Scripts\python.exe .\backend\manage.py createsuperuser
.\env\Scripts\python.exe .\backend\manage.py check
```

Follow the prompts to choose your administrator username and password. There are no built-in login credentials or seeded employee records. Migrations create all application tables and the **Managers** group. An existing `backend/db.sqlite3` file is not used by the normal application configuration.

### 5. Install frontend dependencies

```powershell
cd frontend
npm ci
cd ..
```

No frontend environment file is needed for the default development setup. During development, the frontend sends requests to `/api/` and Vite proxies them to `http://127.0.0.1:8000`.

For a **built frontend** that should use another backend, copy `frontend/.env.example` to `frontend/.env.local` if that file does not already exist, then set:

```dotenv
VITE_API_URL=http://127.0.0.1:8000
```

This must be the backend origin, without `/api`. It is read at build time; rebuild after changing it. Vite exposes `VITE_` variables to browsers, so they must not contain secrets. Development mode deliberately uses the proxy instead of this value; change `server.proxy` in `frontend/vite.config.js` if your local Django server uses another address.

### macOS/Linux equivalents

The database, environment variables, and npm steps are the same. Replace Windows Python commands with the virtual environment's Unix path:

```bash
python3.10 -m venv env
./env/bin/python -m pip install --upgrade pip
./env/bin/python -m pip install -r backend/backend/requirements.txt
# Copy only when there is no existing configuration, then edit the copied file.
test -f backend/.env || cp backend/.env.example backend/.env
# Create the PostgreSQL role/database and configure backend/.env before migrating.
./env/bin/python backend/manage.py migrate
./env/bin/python backend/manage.py createsuperuser
```

## Run locally

Keep both terminals running. Stop either server with `Ctrl+C`.

### Terminal 1: backend

From the project root:

```powershell
.\env\Scripts\python.exe .\backend\manage.py runserver 127.0.0.1:8000
```

On macOS/Linux:

```bash
./env/bin/python backend/manage.py runserver 127.0.0.1:8000
```

### Terminal 2: frontend

From the project root:

```powershell
cd frontend
npm run dev
```

Open the URL printed by Vite, normally `http://localhost:5173`. If the port is occupied, Vite may select the next available port. Sign in using the administrator account created earlier.

| Location | Default URL |
| --- | --- |
| Main application | `http://localhost:5173/` |
| Manager dashboard | `http://localhost:5173/dashboard` |
| Django admin | `http://127.0.0.1:8000/admin/` |
| REST API base | `http://127.0.0.1:8000/api/` |

Start by adding an employee. Then create their contract, record attendance or leave, and set a salary. **View contract** opens an attached PDF inside the app; **Payroll & payslips → Payslip → Print / save as PDF** opens the payslip print workflow.

### Build and preview the frontend

From `frontend/`:

```powershell
npm run build
npm run preview
```

The build is written to `frontend/dist/`. Preview usually runs on port `4173`; use the URL shown in the terminal. Django must still be running. Preview uses the built `VITE_API_URL`, falling back to `http://127.0.0.1:8000`.

The `predev` and `prebuild` scripts copy PDF.js fonts, character maps, and image decoders into `frontend/public/pdfjs/`. The worker is bundled by Vite. These generated files are ignored by Git; use the npm scripts so assets are prepared automatically.

## Accounts and access

- Choose **Create account** next to Sign in. Enter a username, email address, password and confirmation, then choose **Employee** or **Employer**. Successful signup signs the user in automatically.
- **Employers** must enter a business name. Each signup creates a separate business workspace. These accounts can manage only that business's employees, contracts, attendance, leave, holidays, salaries, payroll and reports. Public signup never grants Django staff or superuser privileges.
- **Employees** can sign in and view their own account page at `/account`. They cannot use the employer API or dashboard. Signup does not link an employee login to an employment record; invitations, company membership and employee self-service are not implemented.
- Existing administrators/staff and users in the **Managers** group retain access to the original workspace. Existing employee and holiday records keep `business=NULL`; new public employer accounts cannot see them. Signup does not transfer or claim existing records, even when names or emails match.
- A Managers-group user does not need staff status for the React dashboard; staff status is needed for Django admin. Django admin remains a privileged administration interface.
- Employee records and login accounts are separate: adding an employee in the dashboard does not create a login.
- Usernames are unique and are used to sign in. Passwords are hashed and checked against Django's password validators. There is no password-reset API.

For the existing Render/Vercel deployment, see [signup rollout instructions](docs/DEPLOYMENT.md).

The frontend stores the JWT access token in browser local storage. Access tokens last **30 minutes**; refresh tokens last **one day**. The API provides token refresh, but the current frontend does not automatically use it: an expired session requires signing in again. Signing out removes the browser's stored access token; there is no server-side token revocation endpoint.

## API documentation

### Conventions

- Base URL: `http://127.0.0.1:8000/api/`.
- Keep the trailing slash on all endpoints.
- Use JSON for ordinary requests and `multipart/form-data` for file uploads.
- Send `Authorization: Bearer <access-token>` on protected requests.
- Use dates in `YYYY-MM-DD` format and employee IDs as integer foreign keys.
- Monetary amounts use decimal arithmetic on the server and are returned as decimal strings. Send values such as `"250000.00"`.
- List endpoints currently return unpaginated JSON arrays. Dashboard searching and status filtering happen in the browser; there are no documented server-side list search/filter parameters.
- IDs, timestamps, calculated amounts, and derived display fields are read-only.

### Authentication endpoints

| Method | Endpoint | Request | Success |
| --- | --- | --- | --- |
| POST | `/api/token/` | `username`, `password` | `200` with `access` and `refresh` |
| POST | `/api/token/refresh/` | `refresh` | `200` with a new `access` token |
| POST | `/api/signup/` | `username`, `email`, `password`, `password_confirm`, `role`; `business_name` required for `employer` | `201` with `access`, `refresh`, `user` |
| GET | `/api/account/` | Bearer access token | `200` with `id`, `username`, `email`, `role`, `business_name`, `can_manage` |

Example login body:

```json
{
  "username": "your_admin_username",
  "password": "your_admin_password"
}
```

Signup and both token endpoints are available without an access token. Signup accepts only `employee` or `employer` roles, requires matching passwords, and limits requests by IP using DRF's anonymous throttle (20/hour with the configured cache). Business names must be nonblank for employers and empty/omitted for employees. Duplicate usernames and invalid fields return `400`; throttled requests return `429`.

Token issuance checks credentials; business endpoints additionally require employer/manager access and scope all reads, writes, files and reports to the account's workspace. Django's `/api-auth/` URLs are present, but the business API uses JWT authentication, not an admin browser session.

### Standard CRUD operations

Each resource below supports the following operations. Replace `{resource}` and `{id}` with the appropriate values.

| Method | Endpoint | Action | Success |
| --- | --- | --- | --- |
| GET | `/api/{resource}/` | List records | `200` |
| POST | `/api/{resource}/` | Create a record | `201` |
| GET | `/api/{resource}/{id}/` | Retrieve a record | `200` |
| PUT | `/api/{resource}/{id}/` | Update a record, including required fields | `200` |
| PATCH | `/api/{resource}/{id}/` | Update selected fields | `200` |
| DELETE | `/api/{resource}/{id}/` | Delete an eligible record | `204`, empty body |

| Resource | Required fields when creating | Optional fields / defaults |
| --- | --- | --- |
| `employees` | `first_name`, `last_name`, `email`, `department`, `job_title`, `date_joined` | `phone`, `address`, `emergency_contact`, `manager_name`, `job_description`, `employment_type` (`full_time`), `is_active` (`true`), `photo`, `contract_document`, `contract_title` |
| `contracts` | `employee`, `title`, `start_date` | `end_date` (`null`, ongoing), `status` (`active`), `terms`, `document` |
| `attendance` | `employee`, `date` | `status` (`present`), `hours_worked` (`0` in the API), `notes` |
| `leave` | `employee`, `start_date`, `end_date` | `leave_type` (`annual`), `reason`, `status` (`pending`), `decision_notes` |
| `holidays` | `name`, `date` | `notes` |
| `salaries` | `employee`, `monthly_amount`, `effective_date` | `currency` (`RWF`), `notes` |
| `payroll` | `employee`, `period_start`, `period_end`, `base_salary` | `allowances` (`0`), `deductions` (`0`), `currency` (`RWF`), `status` (`draft`), `paid_date` (`null`), `notes` |

Additional returned fields include `employee_name` for employee-linked records; `photo_name` and `latest_contract` for employees; `document_name` for contracts; and `gross_pay`, `net_pay`, `employee_email`, `department`, and `job_title` for payroll. Payroll identity fields are stored snapshots. `latest_contract` is the most recently added contract with an attachment, not necessarily the active contract.

### Values and validation rules

| Field or workflow | Accepted values / rule |
| --- | --- |
| Employee `employment_type` | `full_time`, `part_time`, `contract`, `intern` |
| Employee `email` | Valid email, unique within the business workspace |
| Contract `status` | `draft`, `active`, `ended` |
| Attendance `status` | `present`, `remote`, `absent` |
| Attendance hours | Decimal from 0 to 24; absent records require zero hours; one record per employee/date |
| Leave `leave_type` | `annual`, `sick`, `family`, `unpaid`, `other` |
| Leave `status` | `pending`, `approved`, `rejected` |
| Dates | End dates cannot precede start dates; attendance and leave cannot precede the employee's joining date |
| Leave conflicts | Pending/approved leave requests cannot overlap; approved leave and attendance cannot cover the same date |
| Holiday dates | One company holiday per date |
| Salary | One current salary record per employee; amounts cannot be negative |
| Currency | `RWF`, `ZAR`, `USD`, `EUR`, `GBP`, `BWP`, `NAD`, `LSL`, `SZL`, `KES`, `NGN`; default `RWF` |
| Payroll | No overlapping pay periods per employee; deductions cannot exceed gross pay |
| Payment status | `draft` or `paid`; paid records require a payment date no later than the server's current date |
| Deletion | Employees with linked employment records cannot be deleted; set `is_active=false` instead. Paid payroll records cannot be changed or deleted. |

### Additional endpoints and file uploads

| Method | Endpoint | Purpose | Success |
| --- | --- | --- | --- |
| GET | `/api/employees/{id}/photo/` | Read the private profile image | `200`, image bytes |
| GET | `/api/contracts/{id}/preview/` | Read private contract bytes for the in-app PDF renderer | `200`, `application/octet-stream`, no download header |
| GET | `/api/contracts/{id}/document/` | Explicitly download a contract | `200`, attachment response |
| POST | `/api/salaries/{id}/mark_paid/` | Create a paid payroll record from a salary | `201`, payroll JSON |
| GET | `/api/reports/` | Retrieve manager reports | `200`, report JSON |

These endpoints all require manager access. Missing records or missing files return `404`.

For file uploads, let the HTTP client generate the multipart boundary; do not manually set `Content-Type` when sending browser `FormData`.

- **Employee photos:** field `photo`, JPG/JPEG/PNG/WEBP, up to 5 MB. The backend validates image contents as well as extensions.
- **Contract files:** field `document` on contracts, or `contract_document` on employee create/update, PDF/DOC/DOCX, up to 10 MB. Upload validation checks extension and size; PDF readability is checked when the viewer opens it.
- **Employee form attachments:** `contract_title` is optional and defaults to `Employment contract`. Each upload creates a new active contract beginning on the employee's joining date, with no end date; it does not overwrite another contract row.
- **Responses:** uploads are write-only fields. Responses expose file names, not public file URLs. Use the authenticated endpoints above to retrieve bytes.
- **PDF viewing:** the application renders PDF pages itself, including password prompts for encrypted PDFs. No external PDF viewer service or download manager is required. Word files must be downloaded, or uploaded as PDF for in-app viewing.

### Employee CRUD example

This PowerShell example talks directly to Django, without the frontend. Use an administrator/manager login and change the example email if it is already in use. It creates and then deletes one demonstration employee.

```powershell
$apiBase = "http://127.0.0.1:8000/api"
$credentials = Get-Credential -Message "Enter your manager or admin login"
$loginBody = @{
    username = $credentials.UserName
    password = $credentials.GetNetworkCredential().Password
} | ConvertTo-Json
$tokens = Invoke-RestMethod -Method Post -Uri "$apiBase/token/" -ContentType "application/json" -Body $loginBody
$headers = @{ Authorization = "Bearer $($tokens.access)" }

$employeeBody = @{
    first_name = "Demo"
    last_name = "Employee"
    email = "demo.employee@example.com"
    department = "Operations"
    job_title = "Assistant"
    date_joined = "2026-01-01"
} | ConvertTo-Json
$employee = Invoke-RestMethod -Method Post -Uri "$apiBase/employees/" -Headers $headers -ContentType "application/json" -Body $employeeBody

Invoke-RestMethod -Method Get -Uri "$apiBase/employees/" -Headers $headers
Invoke-RestMethod -Method Get -Uri "$apiBase/employees/$($employee.id)/" -Headers $headers

$changes = @{ job_title = "Senior assistant" } | ConvertTo-Json
Invoke-RestMethod -Method Patch -Uri "$apiBase/employees/$($employee.id)/" -Headers $headers -ContentType "application/json" -Body $changes

Invoke-RestMethod -Method Delete -Uri "$apiBase/employees/$($employee.id)/" -Headers $headers
```

### Payroll and payment examples

Create draft payroll with `POST /api/payroll/`:

```json
{
  "employee": 1,
  "period_start": "2026-09-01",
  "period_end": "2026-09-30",
  "base_salary": "250000.00",
  "allowances": "10000.00",
  "deductions": "15000.00",
  "currency": "RWF",
  "status": "draft"
}
```

The response includes `gross_pay: "260000.00"` and `net_pay: "245000.00"`. To record payment, `PATCH /api/payroll/{id}/` with:

```json
{
  "status": "paid",
  "paid_date": "2026-09-24"
}
```

Use the actual payment date. After payment is recorded, amounts and payslip identity fields are locked through the API.

For the salary shortcut, send `POST /api/salaries/{id}/mark_paid/` with:

```json
{
  "month": "2026-09",
  "paid_date": "2026-09-24"
}
```

Both fields are optional: `month` defaults to the server's current month, and `paid_date` defaults to today. This creates a paid payroll record for the entire calendar month, using the current stored salary, its currency, and zero allowances/deductions. It rejects inactive employees and periods already covered by payroll, including drafts. Use the regular payroll form when amounts need adjustment. This shortcut does not select historical salaries or prorate pay.

### Reports

```http
GET /api/reports/?date=2026-09-24&days=30
Authorization: Bearer <access-token>
```

| Parameter | Default | Meaning |
| --- | --- | --- |
| `date` | Server's current date | Date to assess attendance, leave, and contract status |
| `days` | `30` | Contract expiry window; integer from 1 to 365. Dashboard choices are 30, 60, and 90. |

The response includes:

- `date`, `month_start`, `contract_window_end`, `working_day`.
- `active_employees`, `departments`, `present_count`, `pending_leave_count`.
- `absent`: employees explicitly recorded absent on the selected date.
- `on_leave`: approved leave covering that date.
- `unrecorded`: active employees with no attendance or approved leave on an expected working day.
- `holidays`: company holidays on the selected date.
- `expiring_contracts`: active contracts for active employees ending between the selected date and the window end, inclusive.
- `expired_contracts`: contracts still marked active whose end date has passed, for active employees.
- `working_hours`: summed hours per employee from the first of the selected month through the report date.
- `payroll_totals`: gross, deductions, net, paid, and draft totals grouped by currency for pay periods **ending** from the first of the month through the report date.

### Errors and HTTP status codes

| Code | Meaning |
| --- | --- |
| `200` | Successful read, update, login, refresh, or report |
| `201` | Record created |
| `204` | Record deleted; no response body |
| `400` | Validation failure, duplicate/conflicting records, protected deletion, or attempt to change paid payroll |
| `401` | Missing, invalid, or expired JWT; invalid login credentials |
| `403` | Authenticated user lacks manager access |
| `404` | Record or attachment not found |
| `405` | HTTP method not supported by the endpoint |

Validation errors commonly use field names or `non_field_errors`:

```json
{"email": ["Enter a valid email address."]}
```

Authentication and lookup failures commonly use `detail`; some workflow errors are arrays of messages. The frontend handles these formats and reports network failures separately. Unexpected server errors may return `500`; inspect Django's terminal output to diagnose them.

## Checks and tests

From the project root:

```powershell
.\env\Scripts\python.exe .\backend\manage.py check
.\env\Scripts\python.exe .\backend\manage.py showmigrations api
.\env\Scripts\python.exe .\backend\manage.py test api --settings=backend.test_settings --noinput
```

The checked-in API suite currently contains **51 tests**, covering signup/login, account roles, business isolation, CORS, profiles/uploads, private files, attendance/leave validation, payroll, and reports. Test settings use an isolated in-memory SQLite database and a fast test-only password hasher. They still import base settings, so provide `SECRET_KEY` when `DEBUG=false` and either `DATABASE_URL` or the five `DB_*` variables. PostgreSQL need not be running for this test command. Do not run the application with `backend.test_settings`.

Running tests without `--settings=backend.test_settings` uses PostgreSQL and requires a role allowed to create a test database. The normal application role does not require that privilege.

From `frontend/`:

```powershell
npm run lint
npm run build
```

For a manual end-to-end check: sign in, create/edit a demonstration employee, upload and view a PDF, record attendance, add leave on another day, set a salary, create draft payroll, preview its payslip, and inspect reports. Delete the demonstration employee before attaching related records if you want to exercise permanent deletion; employees with linked records must instead be marked inactive.

## Technical decisions and assumptions

### Application structure

- React handles navigation and forms; `src/api.js` centralizes authentication headers, JSON/multipart requests, and error messages.
- Django REST Framework viewsets provide CRUD routes. Serializers validate requests, and permission classes enforce manager access on the server.
- PostgreSQL stores relational records; Django migrations track schema changes. Use the dashboard/API for the documented workflow validation. Payroll is read-only in Django admin.
- Shared form configurations and reusable record/report tables keep the manager sections consistent. The current dashboard loads complete lists; pagination and server-side search are not implemented.

### Employment and attendance

- Public employer accounts have separate business workspaces. Existing administrators and Managers-group accounts share the original workspace. There is no department-specific manager scope or public joining/claiming of existing businesses.
- Employee status is the current `is_active` flag; historical reports also use that current status, rather than reconstructing a past employment state.
- Expected working days are Monday to Friday, excluding manually entered company holidays. Missing attendance is shown separately from confirmed absence. Individual shift schedules and holiday imports are not implemented.
- Working hours are entered manually. The frontend starts a present-day entry at eight hours; the API's default is zero. There is no automatic clock-in/out, overtime calculation, or attendance-to-payroll calculation.
- Approved leave blocks conflicting attendance. Leave balances, accrual, statutory entitlement calculations, and employee self-service requests are not implemented.
- Server dates use `TIME_ZONE = "UTC"`; frontend default dates use the browser's local date. This can differ near midnight.

### Salaries and payroll

- The current default currency is **RWF**. Other supported currencies can be selected per salary/payroll record; there is no exchange-rate conversion. Reports never add different currencies into one total.
- A salary row stores the employee's current monthly amount, not a full salary history. Existing payroll records retain their saved amounts.
- `gross_pay = base_salary + allowances`; `net_pay = gross_pay - deductions`.
- Tax, statutory deductions, overtime pay, and partial-month calculations are entered manually. Paid status records a payment made elsewhere; it does not transfer funds or connect to a bank.
- Paid payroll records preserve employee identity/job snapshots and cannot be edited or deleted through the API. Payslips are rendered from these records in the frontend and printed/saved by the browser; there is no separate payslip-file API or automatic email delivery.

### File storage

- Files are stored on the backend filesystem under `backend/private_media/`; the database stores references. Back up both the database and this directory.
- File access goes through authenticated API endpoints. Do not expose `private_media` as a public static/media directory.
- Replacing an existing profile photo or a contract's document removes the previous stored file. Deleting a database row leaves its file on disk; there is no automatic orphan-file cleanup.
- PDF rendering occurs locally in the browser, using bundled PDF.js and local supporting assets. Contract data is not sent to an external viewer.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `KeyError: DB_NAME` or another database variable | Create/edit `backend/.env` with all five required variables. |
| PostgreSQL connection refused | Start PostgreSQL and verify `DB_HOST` and `DB_PORT`. |
| Password authentication failed | Match `DB_USER`/`DB_PASSWORD` to the PostgreSQL role. |
| Missing tables or columns | Run `manage.py migrate` against the intended database. |
| Permission denied while migrating | Ensure the application role owns its database or has the necessary schema privileges. |
| Django module not found | Use `env`'s Python and install `backend/backend/requirements.txt`. |
| PowerShell blocks `npm.ps1` | Use `npm.cmd ci` or `npm.cmd run dev`; no execution-policy change is required. |
| `npm` reports missing scripts | Run it from `frontend/`, not the project root. |
| Unsupported Node engine | Check `node --version` against the prerequisite above. |
| Frontend cannot reach Django / proxy returns 502 | Keep Django running on port 8000 or update Vite's proxy target, then restart Vite. |
| Correct credentials but access denied | Give the account Managers-group membership or appropriate admin/staff access. |
| Redirected to sign-in after some time | The 30-minute access token may have expired; sign in again. |
| Employee deletion is blocked | Linked records exist; edit the profile and turn off Active employee. |
| Contract PDF will not display | Use View/View contract, check the file is a readable PDF, and run the npm dev/build script to prepare local PDF assets. DOC/DOCX files require download or PDF conversion. |
| File endpoint returns 404 | The attachment is missing from the record or from `backend/private_media/`. |
| PostgreSQL tests cannot create a database | Use the documented isolated SQLite test command. |

## Deployment considerations

Django reads production settings from environment variables, including `SECRET_KEY`, `DEBUG`, `DATABASE_URL`, `ALLOWED_HOSTS`, `FRONTEND_URL`, and `CORS_ALLOWED_ORIGINS`. Render defaults to `DEBUG=false` and automatically contributes its hostname to allowed hosts. Set `FRONTEND_URL` to the exact frontend origin (no path or `#sign-in`); this adds it to CORS and trusted CSRF origins. Additional frontend origins can be listed in `CORS_ALLOWED_ORIGINS`, separated by commas. See [deployment instructions](docs/DEPLOYMENT.md) for the current services and signup migration.

Build the frontend with the intended `VITE_API_URL`. Its host must serve `index.html` for client-side routes such as `/dashboard/employees`. Preserve the built PDF assets, keep the private uploads directory persistent and non-public, and plan backups of PostgreSQL and uploaded files. Django's `runserver` and Vite's development/preview servers are local development tools.
