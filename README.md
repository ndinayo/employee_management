# Employee Management System

A multi-tenant employee management platform. One deployment serves many
companies: each company's employer runs their own workspace, their employees
reach only their own records, and a single platform owner (super admin) manages
the companies themselves.

React frontend, Django REST Framework backend, PostgreSQL, JWT authentication.

## Contents

- [Features](#features)
- [Technology stack](#technology-stack)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Running locally](#running-locally)
- [Roles and accounts](#roles-and-accounts)
- [API documentation](#api-documentation)
- [Tests and checks](#tests-and-checks)
- [Building](#building)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

## Features

**Super admin (platform owner)**

- Platform dashboard: company counts by status, employers, employees, usage over
  today / 7 days / 30 days, month-on-month growth with a 12-month chart, and
  total platform users. Every figure is counted from live rows.
- Company lifecycle: recent registrations, companies awaiting verification,
  recently suspended, and companies dormant for over 60 days.
- Company management: create a company with its employer in one step, change a
  company's status (`pending` / `active` / `suspended`), or delete it entirely.
- Account issues: employers who never signed in, suspended and disabled
  accounts, companies with no employer, and failed invitation emails.
- Platform health: live database ping with latency, email sender state, real
  disk usage, and version/runtime information.
- Two-way messaging with any company, by dashboard message or by email.

**Employer (company workspace)**

- Employees, contracts (draft, send for signature, approve, terminate),
  attendance and shifts, leave requests and yearly allocations, company
  holidays, announcements, a company calendar, salaries, and payroll/payslips.
- Reports roll-up for a chosen date.
- Google Meet scheduling, and a conversation with the platform team.

**Employee**

- Own profile, attendance clock-in/out, leave requests, contract signing,
  announcements and the company calendar.

Employees reach the workspace only after their employer approves their signed
contract. The super admin never sees a company's attendance, leave, payroll,
contracts, salaries, holidays or announcements; those stay with the employer.

## Technology stack

| Layer | Implementation |
| --- | --- |
| Frontend | React 19, React Router 7, Vite 8, plain CSS |
| Backend | Django 5.2, Django REST Framework, Simple JWT |
| Database | PostgreSQL, through the Django ORM and migrations |
| API docs | drf-spectacular (Swagger UI and ReDoc, served by the backend) |
| Django admin | Jazzmin |
| Files | Private local storage by default, optional S3 via django-storages |
| PDF | PDF.js in the browser for contract previews |
| Server | Gunicorn with WhiteNoise for static files |

## Project structure

```text
employee_management/
├── README.md
├── .python-version                 # Pins 3.12 for deployment platforms
├── backend/
│   ├── manage.py
│   ├── .env.example                # Copy to backend/.env
│   ├── build.sh                    # Deployment build
│   ├── start.sh                    # Deployment start (migrate, then gunicorn)
│   ├── backend/
│   │   ├── settings.py             # Includes the drf-spectacular configuration
│   │   ├── test_settings.py        # In-memory SQLite, for tests only
│   │   ├── urls.py                 # All routes, including /api/docs/
│   │   ├── health.py               # Public readiness probe
│   │   └── requirements.txt
│   ├── api/
│   │   ├── models.py               # Business, AccountProfile, Employee, ...
│   │   ├── views.py                # Employer workspace viewsets
│   │   ├── accounts.py             # Auth, account, and /api/me/ endpoints
│   │   ├── platform.py             # Super admin: companies, employers, employees
│   │   ├── dashboard.py            # Super admin: overview and platform health
│   │   ├── messaging.py            # Platform/company conversations
│   │   ├── serializers.py
│   │   ├── permissions.py          # IsManager, IsAdmin
│   │   ├── onboarding.py           # Account provisioning and email
│   │   ├── schema.py               # Documentation-only schema helpers
│   │   ├── leave_management.py
│   │   ├── contract_content.py
│   │   ├── management/commands/    # bootstrap_admin, ensure_platform_admin
│   │   ├── migrations/
│   │   └── test_*.py, tests.py
│   └── private_media/              # Created on first upload; not public
├── frontend/
│   ├── package.json                # The frontend app lives here
│   ├── .env.example                # Only needed for a built frontend
│   ├── vite.config.js              # Dev proxy: /api -> 127.0.0.1:8000
│   ├── vercel.json                 # SPA rewrites for client-side routing
│   ├── scripts/copy-pdf-assets.mjs
│   └── src/
│       ├── App.jsx                 # Routes and site chrome
│       ├── AccountPage.jsx         # Employee workspace
│       ├── ManagerDashboard.jsx    # Employer workspace
│       ├── CompanyCalendar.jsx
│       ├── api.js                  # Every API call, with JWT refresh
│       └── components/
│           ├── AdminDashboard.jsx  # Super admin shell
│           ├── PlatformOverview.jsx
│           └── Conversation.jsx
└── docs/
    ├── API.md                      # Human-readable API guide
    ├── DEPLOYMENT.md
    ├── openapi.yaml                # Generated schema snapshot
    └── openapi.json
```

Install frontend dependencies from `frontend/`. The root `package.json` is not
the frontend application and holds none of its scripts.

## Prerequisites

| Tool | Version | Notes |
| --- | --- | --- |
| Python | 3.10 or newer | The checked-in virtual environment runs 3.10; `.python-version` asks deployment platforms for 3.12 |
| Node.js | 20 or newer | Developed against Node 22 and npm 10 |
| PostgreSQL | 13 or newer | Required. SQLite is used only by the test settings |
| Git | any recent | |

## Setup

### 1. Clone the repository

```bash
git clone <your-repository-url> employee_management
cd employee_management
```

### 2. Create and activate a virtual environment

**Windows (PowerShell)**

```powershell
py -3 -m venv env
.\env\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

**macOS / Linux**

```bash
python3 -m venv env
source env/bin/activate
python -m pip install --upgrade pip
```

Activation is optional. Every command below can instead be run against the
environment's interpreter directly, which is useful in scripts:
`.\env\Scripts\python.exe` on Windows, `./env/bin/python` elsewhere.

### 3. Install backend dependencies

Note the doubled `backend` in the path: the requirements file lives inside the
Django project package.

```bash
python -m pip install -r backend/backend/requirements.txt
```

### 4. Create the PostgreSQL database

Connect as a PostgreSQL administrator:

```bash
psql -h 127.0.0.1 -U postgres -d postgres
```

Run this once for a new installation, choosing your own password:

```sql
CREATE USER employee_app WITH PASSWORD 'replace-with-your-local-password';
CREATE DATABASE employee_management OWNER employee_app;
```

The application role owns the database so Django can create and alter its
tables. It does not need superuser rights. Leave `psql` with `\q`.

If `psql` is not on PATH, run the same SQL from pgAdmin's Query Tool against the
`postgres` database. `CREATE DATABASE` must run outside a transaction.

### 5. Configure environment variables

The backend reads `backend/.env` (loaded by `python-dotenv` from the `backend/`
directory). Copy the example only if the file does not already exist:

**Windows (PowerShell)**

```powershell
if (-not (Test-Path .\backend\.env)) { Copy-Item .\backend\.env.example .\backend\.env }
```

**macOS / Linux**

```bash
test -f backend/.env || cp backend/.env.example backend/.env
```

Then edit `backend/.env`:

| Variable | Required | Purpose |
| --- | --- | --- |
| `DB_NAME` | yes | PostgreSQL database name |
| `DB_USER` | yes | Application database role |
| `DB_PASSWORD` | yes | Password for that role |
| `DB_HOST` | yes | PostgreSQL host, commonly `127.0.0.1` |
| `DB_PORT` | yes | PostgreSQL port, commonly `5432` |
| `DATABASE_URL` | no | A single connection URL. When set, it replaces all five `DB_*` values |
| `SECRET_KEY` | only when `DEBUG=false` | Django signing key. Startup fails without it in production |
| `DEBUG` | no | Defaults to `true` locally and `false` on Render |
| `FRONTEND_URL` | no | Where invitation emails send people. Defaults to `http://localhost:5173` in development |
| `ALLOWED_HOSTS` | no | Comma-separated. Defaults to localhost |
| `CORS_ALLOWED_ORIGINS` | no | Comma-separated extra browser origins |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | no | Server-wide invitation sender. Leave blank to let each employer add a Gmail App Password under Settings |
| `MEDIA_ROOT` | no | Where uploads are stored. Defaults to `backend/private_media` |
| `STORAGE_BACKEND` | no | `filesystem` (default) or `s3` |
| `PLATFORM_ADMIN_USERNAME`, `PLATFORM_ADMIN_EMAIL`, `PLATFORM_ADMIN_PASSWORD` | no | Used only by `ensure_platform_admin` to create the initial platform super admin. See step 7 |

`backend/.env` is ignored by Git. Real process environment variables take
precedence over the file.

### 6. Run the migrations

```bash
python backend/manage.py migrate
python backend/manage.py check
```

Migrations create every table. There are no seeded accounts or demo records. An
existing `backend/db.sqlite3` file is not used by the normal configuration.

### 7. Create an administrator account

There are two different things called "admin", and they are not the same:

**A Django admin user**, for the Django admin site at `/admin/`:

```bash
python backend/manage.py createsuperuser
```

**A platform super admin**, for the `/api/admin/...` endpoints and the super
admin dashboard. This requires an `AccountProfile` with `role="admin"`, which
`createsuperuser` does not create. Either create the profile from the Django
admin site, or create the initial platform super admin from environment
variables. Set all three, in `backend/.env` or the process environment:

| Variable | Purpose |
| --- | --- |
| `PLATFORM_ADMIN_USERNAME` | Username for the platform super admin |
| `PLATFORM_ADMIN_EMAIL` | Email address for that account (it can also sign in with it) |
| `PLATFORM_ADMIN_PASSWORD` | Initial password. It must pass Django's password validation |

Then run:

```bash
python backend/manage.py ensure_platform_admin
```

The command creates a Django superuser with a platform admin profile. With none
of the variables set it does nothing, and with only some of them set it fails
without changing anything. It never resets the password or modifies an account
that already exists, and it refuses to promote an existing account that is not
already a platform admin. It does not run automatically during deployment.
Remove `PLATFORM_ADMIN_PASSWORD` from the environment once the account exists,
and never commit real values for these variables.

A third command, `bootstrap_admin`, creates a Django superuser from
`DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD` and
`DJANGO_SUPERUSER_EMAIL` if they are set. It never changes an existing account
and is what `start.sh` runs during deployment.

### 8. Install frontend dependencies

```bash
cd frontend
npm ci
cd ..
```

No frontend environment file is needed for development: Vite proxies `/api` to
`http://127.0.0.1:8000` (see `frontend/vite.config.js`). Only a **built**
frontend pointed at another backend needs one. In that case copy
`frontend/.env.example` to `frontend/.env.local` and set the backend origin
without a trailing `/api`:

```dotenv
VITE_API_URL=http://127.0.0.1:8000
```

This is read at build time, so rebuild after changing it. Vite exposes every
`VITE_` variable to the browser, so never put a secret in one.

## Running locally

Two terminals.

**Terminal 1, backend** (from the project root):

```bash
python backend/manage.py runserver
```

**Terminal 2, frontend**:

```bash
cd frontend
npm run dev
```

| Service | URL |
| --- | --- |
| Frontend | <http://localhost:5173/> |
| Backend API | <http://127.0.0.1:8000/api/> |
| Swagger UI | <http://127.0.0.1:8000/api/docs/> |
| ReDoc | <http://127.0.0.1:8000/api/redoc/> |
| Django admin | <http://127.0.0.1:8000/admin/> |
| Health probe | <http://127.0.0.1:8000/api/health/> |

`npm run dev` first runs `copy-pdf-assets.mjs`, which copies the PDF.js worker
into `frontend/public`. Contract previews need it.

## Roles and accounts

Authentication is **JWT bearer tokens**. `POST /api/token/` accepts a username
or an email address and returns `access` (30 minutes) and `refresh` (1 day).
Send `Authorization: Bearer <access>` on every protected request;
`frontend/src/api.js` refreshes the token automatically.

Every account has exactly one role on its `AccountProfile`. The roles do not
overlap: an admin token is rejected by employer endpoints and vice versa.

| Role | Represents | Reaches |
| --- | --- | --- |
| `admin` | The platform owner, who runs the whole deployment | `/api/admin/...` and the super admin dashboard at `/admin` in the frontend |
| `employer` | One company, which owns its own workspace | The employer workspace endpoints and `/api/messages/` |
| `employee` | One person employed by a company | Only `/api/me/...`, and only after their employer approves their signed contract |

Employer data is scoped to that employer's own business. A record belonging to
another business returns `404`, never `403`.

A company also has a status of its own, changed only by the super admin:

| Status | Meaning |
| --- | --- |
| `pending` | Signed itself up and is not verified yet. A queue for the admin; the workspace stays open |
| `active` | Verified and running |
| `suspended` | The company's employer sign-ins are deactivated. Nothing is deleted |

Employers who sign up through the public form arrive as `pending`. Companies the
super admin creates are `active` immediately.

## API documentation

The full reference is generated from the code by drf-spectacular, so it cannot
drift from the implementation.

| What | Path | Local URL |
| --- | --- | --- |
| Swagger UI | `/api/docs/` | <http://127.0.0.1:8000/api/docs/> |
| ReDoc | `/api/redoc/` | <http://127.0.0.1:8000/api/redoc/> |
| OpenAPI YAML | `/api/schema/` | <http://127.0.0.1:8000/api/schema/> |
| OpenAPI JSON | `/api/schema/?format=json` | <http://127.0.0.1:8000/api/schema/?format=json> |

The same paths work on a deployed backend, for example
`https://your-backend-host/api/docs/`. No host is baked into the schema: Swagger
UI loads `/api/schema/` relatively, so one build serves every environment.

[docs/API.md](docs/API.md) is the human-readable guide: authentication,
roles and permissions, error codes, request examples, and the complete endpoint
list grouped by feature. Snapshots of the schema are checked in as
[docs/openapi.yaml](docs/openapi.yaml) and [docs/openapi.json](docs/openapi.json).

### Testing the API from Swagger

1. Open <http://127.0.0.1:8000/api/docs/>.
2. Expand **Authentication**, then **POST /api/token/**, press **Try it out**,
   send your username and password, and copy the `access` value.
3. Press **Authorize** at the top of the page and paste the token into
   `jwtAuth`.
4. Any protected operation now sends the header for you. Authorization survives
   a page reload.

Regenerate the checked-in schema after changing any view, serializer or route,
from `backend/`:

```bash
python manage.py spectacular --validate --fail-on-warn --file ../docs/openapi.yaml
python manage.py spectacular --validate --fail-on-warn --format openapi-json --file ../docs/openapi.json
```

## Tests and checks

Backend, from the project root:

```bash
python backend/manage.py check
python backend/manage.py showmigrations api
python backend/manage.py test api --settings=backend.test_settings --noinput
```

`backend.test_settings` uses an isolated in-memory SQLite database and a fast
test-only password hasher, so PostgreSQL need not be running. It still imports
the base settings, so supply `SECRET_KEY` when `DEBUG=false`, plus either
`DATABASE_URL` or the five `DB_*` variables. Never run the application itself
with `backend.test_settings`.

Running the tests without `--settings=backend.test_settings` uses PostgreSQL and
needs a role allowed to create a test database, which the application role does
not have by default.

Frontend, from `frontend/`:

```bash
npm run lint
npm run build
```

## Building

```bash
cd frontend
npm run build      # Outputs to frontend/dist
npm run preview    # Serves the build locally
```

The backend collects its own static files for deployment:

```bash
python backend/manage.py collectstatic --noinput
```

## Deployment

Based on the configuration committed to this repository.

**Backend (Render).** `backend/build.sh` installs requirements and runs
`collectstatic`. `backend/start.sh` runs `migrate`, then `bootstrap_admin`, then
Gunicorn on `$PORT`. Render settings, taken from
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md):

| Setting | Value |
| --- | --- |
| Root directory | `backend` |
| Build command | `bash build.sh` |
| Start command | `bash start.sh` |
| Health check path | `/api/health/` |

Set at minimum `SECRET_KEY`, `DATABASE_URL`, `FRONTEND_URL` and
`CORS_ALLOWED_ORIGINS`. `DEBUG` defaults to `false` on Render, which also
contributes its own hostname to `ALLOWED_HOSTS`. `FRONTEND_URL` must be the
exact frontend origin with no path; it is added to CORS and trusted CSRF
origins.

**Frontend (Vercel).** `frontend/vercel.json` sets the build command, output
directory, and the SPA rewrite that serves `index.html` for client-side routes
such as `/dashboard/employees` and `/admin/companies`. Build with the intended
`VITE_API_URL`.

Keep `private_media` on persistent, non-public storage, or set
`STORAGE_BACKEND=s3`. Plan backups for both PostgreSQL and uploaded files.
Django's `runserver` and Vite's dev and preview servers are development tools
only.

## Troubleshooting

**`django.db.utils.OperationalError` on any command.** PostgreSQL is not
running, or `backend/.env` has the wrong host, port, user or password. Confirm
with `psql -h 127.0.0.1 -U employee_app -d employee_management`.

**`ImproperlyConfigured: Set SECRET_KEY before starting with DEBUG=false`.** Set
`SECRET_KEY` in the environment, or leave `DEBUG=true` for local development.

**`ModuleNotFoundError: No module named 'dj_database_url'`.** The system Python
is being used instead of the virtual environment. Activate it, or call
`./env/bin/python` (or `.\env\Scripts\python.exe`) explicitly.

**`relation "api_..." does not exist`, or a 500 from a new feature.** A
migration has not been applied. Run `python backend/manage.py showmigrations api`
and then `python backend/manage.py migrate`.

**Signed in as the super admin but there is no dashboard.** The account has no
`AccountProfile` with `role="admin"`. See
[Create an administrator account](#7-create-an-administrator-account).

**Invitation emails never arrive.** No sender is configured. Check
`GET /api/admin/health/`, or the Platform health panel on the super admin
dashboard, which reports the email service state. Either set the `EMAIL_*`
variables or add a Gmail App Password under the employer's Settings page.

**Frontend loads but every request fails with CORS or 401.** The backend is not
running on `http://127.0.0.1:8000`, or a built frontend has the wrong
`VITE_API_URL`. In development the Vite proxy in `frontend/vite.config.js`
handles this; change `server.proxy` if your backend uses another address.

**A deep link such as `/admin/companies` 404s in production.** The host is not
rewriting unknown paths to `index.html`. `frontend/vercel.json` already does
this; any other host needs the same rule.
