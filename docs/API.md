# API guide

A human-readable companion to the generated OpenAPI schema. Everything here is
taken from the schema the running project produces, so the two stay in step.

- **Base path** every endpoint shares: `/api/`
- **Schema version**: OpenAPI 3.0.3, API version 1.0.0
- **Documented**: 69 paths, 122 operations

## Where the interactive documentation lives

The documentation is served by the backend itself, so the host is whatever host
the backend runs on. No absolute URL is baked into the schema: Swagger UI loads
`/api/schema/` relatively, which means the same build works locally and on a
deployed backend without configuration.

| What | Path | Local example |
| --- | --- | --- |
| Swagger UI (try endpoints, with an Authorize button) | `/api/docs/` | <http://127.0.0.1:8000/api/docs/> |
| ReDoc (reference layout) | `/api/redoc/` | <http://127.0.0.1:8000/api/redoc/> |
| OpenAPI schema, YAML | `/api/schema/` | <http://127.0.0.1:8000/api/schema/> |
| OpenAPI schema, JSON | `/api/schema/?format=json` | <http://127.0.0.1:8000/api/schema/?format=json> |

On a deployed backend the same paths apply, for example
`https://your-backend-host/api/docs/`.

A snapshot of the schema is checked into this folder as
[openapi.yaml](openapi.yaml) and [openapi.json](openapi.json). Regenerate both
after changing any view, serializer or route, from the `backend/` directory:

```bash
python manage.py spectacular --validate --fail-on-warn --file ../docs/openapi.yaml
python manage.py spectacular --validate --fail-on-warn --format openapi-json --file ../docs/openapi.json
```

`--fail-on-warn` is deliberate: the schema currently generates with zero
warnings and zero errors, and keeping it that way is the point of the flag.

## Authentication

The API uses **JWT bearer tokens** (`djangorestframework-simplejwt`). There are
no sessions and no API keys.

1. `POST /api/token/` with a username **or** an email address, plus a password.
2. The response carries `access` and `refresh`.
3. Send the access token on every protected request:
   `Authorization: Bearer <access>`.
4. Access tokens last **30 minutes**; refresh tokens last **1 day**.
   Exchange a refresh token at `POST /api/token/refresh/`.

```bash
curl -X POST http://127.0.0.1:8000/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "you@example.com", "password": "your-password"}'
```

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": { "id": 1, "username": "you", "role": "employer", "can_manage": true }
}
```

```bash
curl http://127.0.0.1:8000/api/account/ \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

### Trying endpoints from Swagger UI

1. Open `/api/docs/`.
2. Expand **Authentication**, then **POST /api/token/**, press **Try it out**,
   send your username and password, and copy the `access` value.
3. Press **Authorize** at the top of the page, paste the token into `jwtAuth`,
   and confirm.
4. Every protected operation now sends the `Authorization` header for you.
   Authorization persists across page reloads.

An account created by an employer comes back with `must_change_password: true`
and must call `POST /api/account/password/` before the rest of the API is useful.

## Roles and permissions

Every account has exactly one role, stored on its `AccountProfile`. The roles do
not overlap: an admin token is rejected by employer endpoints, and vice versa.

| Role | Reaches | Enforced by |
| --- | --- | --- |
| `admin` | `/api/admin/...`: the platform dashboard and health, companies, employers, every employee, and messages from companies | `IsAdmin` |
| `employer` | the employer workspace (`/api/employees/`, `/api/contracts/`, `/api/attendance/`, `/api/leave/`, `/api/leave-balances/`, `/api/holidays/`, `/api/announcements/`, `/api/calendar-events/`, `/api/salaries/`, `/api/payroll/`, `/api/reports/`) and `/api/messages/` | `IsManager` |
| `employee` | only `/api/me/...`, and only once the employer has **approved their signed contract** | `IsAuthenticated` plus a contract check |

Employer data is scoped to the signed-in employer's own business. A record that
belongs to another business answers `404`, not `403`, so the existence of other
businesses is never disclosed.

A company carries a lifecycle of its own on its `Business` row, changed only by
the super admin through `PATCH /api/admin/businesses/{id}/`:

| Status | Meaning |
| --- | --- |
| `pending` | Signed itself up and has not been verified yet. A queue for the admin; the workspace stays open. |
| `active` | Verified and running. |
| `suspended` | The company's employer sign-ins are deactivated, so the workspace is closed. Nothing is deleted. |

## Response and error codes

| Code | When |
| --- | --- |
| `200` | Read or update succeeded |
| `201` | Created |
| `204` | Deleted; no body |
| `400` | Validation failed. Body is `{"field": ["message", ...]}` or `{"detail": "message"}` |
| `401` | No token, a malformed token, or an expired one. Obtain a new one from `/api/token/` |
| `403` | Authenticated, but the role is not allowed to use this endpoint |
| `404` | No such record, or it belongs to another business |
| `405` | Method not allowed on this path |
| `429` | Throttled. Signup allows 20/hour and password reset 10/hour, per client |

```json
{ "business_name": ["Enter your business name to create an employer account."] }
```

```json
{ "detail": "Administrator access is required." }
```

## Request examples

Create an employer and its company in one call (super admin):

```bash
curl -X POST http://127.0.0.1:8000/api/admin/employers/ \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -d '{"username": "kigali-books", "email": "owner@kigali-books.example",
       "password": "S0me-strong-passphrase", "business_name": "Kigali Books Ltd"}'
```

Suspend a company, which closes its workspace without deleting anything:

```bash
curl -X PATCH http://127.0.0.1:8000/api/admin/businesses/3/ \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -d '{"status": "suspended"}'
```

Hire an employee (employer). The response carries an `invite` object describing
what happened to the sign-in account and its invitation email:

```bash
curl -X POST http://127.0.0.1:8000/api/employees/ \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -d '{"first_name": "Amina", "last_name": "Uwase", "job_title": "Accountant",
       "email": "amina.uwase@example.com", "date_joined": "2026-10-01"}'
```

Write to the platform team as a company. `channel` chooses the delivery route
and is never both: `message` lands in the recipient's dashboard and sends no
email, `email` goes to their inbox and stays out of their dashboard:

```bash
curl -X POST http://127.0.0.1:8000/api/messages/ \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -d '{"body": "Our invitation emails are not arriving.", "channel": "message"}'
```

Clock in as an employee:

```bash
curl -X POST http://127.0.0.1:8000/api/me/attendance/ \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -d '{"action": "check_in", "shift": "day", "time": "08:05"}'
```

## File uploads and downloads

Uploads use `multipart/form-data`, not JSON:

- `POST /api/contracts/` with a `document` file, and
  `PATCH /api/employees/{id}/` with a `photo` file.
- `GET /api/contracts/{id}/document/` and `GET /api/contracts/{id}/preview/`
  return the stored file and a generated PDF preview.
- `GET /api/employees/{id}/photo/` and `GET /api/me/photo/` return image bytes.

These are served through the API rather than from a public URL, so a bearer
token is required. They cannot be used as a plain `<img src>`.

## Endpoint reference

Generated from the current schema. Every operation below also carries a
description, parameters, request body, response schema and error responses in
Swagger UI and ReDoc.

### Health

**Authentication:** Not required &nbsp;&nbsp; **Role:** None (public)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health/` | Service readiness |


### Authentication

**Authentication:** Not required &nbsp;&nbsp; **Role:** None (public)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/password-reset/` | Request a password reset link |
| `POST` | `/api/password-reset/confirm/` | Set a new password from a reset link |
| `POST` | `/api/signup/` | Create an account |
| `POST` | `/api/token/` | Obtain a JWT pair (sign in) |
| `POST` | `/api/token/refresh/` | Refresh an access token |


### Account

**Authentication:** Bearer JWT &nbsp;&nbsp; **Role:** Any signed-in account

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/account/` | Who am I |
| `GET` | `/api/account/email/` | Read the shared invitation sender |
| `PATCH` | `/api/account/email/` | Configure the shared invitation sender |
| `POST` | `/api/account/password/` | Change your own password |


### Platform administration

**Authentication:** Bearer JWT &nbsp;&nbsp; **Role:** `admin` (super admin)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/admin/businesses/` | List companies |
| `DELETE` | `/api/admin/businesses/{id}/` | Delete a company |
| `PATCH` | `/api/admin/businesses/{id}/` | Change a company's status |
| `GET` | `/api/admin/employees/` | List every employee |
| `POST` | `/api/admin/employees/` | Add an employee to a business |
| `DELETE` | `/api/admin/employees/{id}/` | Delete an employee |
| `GET` | `/api/admin/employees/{id}/` | Retrieve an employee |
| `PATCH` | `/api/admin/employees/{id}/` | Update an employee |
| `GET` | `/api/admin/employers/` | List employers |
| `POST` | `/api/admin/employers/` | Create an employer |
| `GET` | `/api/admin/employers/{id}/` | Retrieve an employer |
| `PATCH` | `/api/admin/employers/{id}/` | Update an employer |
| `GET` | `/api/admin/health/` | Platform health |
| `GET` | `/api/admin/messages/` | List company conversations |
| `POST` | `/api/admin/messages/read-all/` | Mark every company's messages as read |
| `GET` | `/api/admin/messages/{id}/` | Read one company's conversation |
| `POST` | `/api/admin/messages/{id}/` | Write to a company |
| `POST` | `/api/admin/messages/{id}/read/` | Mark a company's messages as read |
| `GET` | `/api/admin/overview/` | Platform overview |


### Employer · Messages

**Authentication:** Bearer JWT &nbsp;&nbsp; **Role:** `employer`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/messages/` | Read this company's conversation with the platform team |
| `POST` | `/api/messages/` | Write to the platform team |
| `POST` | `/api/messages/read/` | Mark the platform team's messages as read |


### Employer · Employees

**Authentication:** Bearer JWT &nbsp;&nbsp; **Role:** `employer`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/employees/` | List employees |
| `POST` | `/api/employees/` | Hire an employee |
| `DELETE` | `/api/employees/{id}/` | Delete an employee |
| `GET` | `/api/employees/{id}/` | Retrieve one employee |
| `PATCH` | `/api/employees/{id}/` | Update an employee |
| `PUT` | `/api/employees/{id}/` | Replace an employee |
| `GET` | `/api/employees/{id}/photo/` | Download an employee's photo |


### Employer · Contracts

**Authentication:** Bearer JWT &nbsp;&nbsp; **Role:** `employer`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/contracts/` | List contracts |
| `POST` | `/api/contracts/` | Create a contract |
| `DELETE` | `/api/contracts/{id}/` | Delete a draft contract |
| `GET` | `/api/contracts/{id}/` | Retrieve one contract |
| `PATCH` | `/api/contracts/{id}/` | Update a draft contract |
| `PUT` | `/api/contracts/{id}/` | Replace a draft contract |
| `POST` | `/api/contracts/{id}/approve-worker/` | Approve the worker to start |
| `GET` | `/api/contracts/{id}/document/` | Download the attached contract file |
| `POST` | `/api/contracts/{id}/initiate-termination/` | Start an employer-led termination |
| `GET` | `/api/contracts/{id}/preview/` | Stream the attached contract file for preview |
| `POST` | `/api/contracts/{id}/request-new-signature/` | Request a corrected signature |
| `POST` | `/api/contracts/{id}/resend-signature-email/` | Email the signature request again |
| `POST` | `/api/contracts/{id}/send-for-signature/` | Send a contract for signature |
| `POST` | `/api/contracts/{id}/termination-decision/` | Approve or reject an employee's termination request |


### Employer · Attendance

**Authentication:** Bearer JWT &nbsp;&nbsp; **Role:** `employer`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/attendance/` | List attendance records |
| `POST` | `/api/attendance/` | Record attendance |
| `DELETE` | `/api/attendance/{id}/` | Delete an attendance record |
| `GET` | `/api/attendance/{id}/` | Retrieve one attendance record |
| `PATCH` | `/api/attendance/{id}/` | Correct an attendance record |
| `PUT` | `/api/attendance/{id}/` | Replace an attendance record |


### Employer · Leave

**Authentication:** Bearer JWT &nbsp;&nbsp; **Role:** `employer`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/leave-balances/` | List leave balances |
| `POST` | `/api/leave-balances/` | Create a leave balance |
| `DELETE` | `/api/leave-balances/{id}/` | Delete a leave balance |
| `GET` | `/api/leave-balances/{id}/` | Retrieve one leave balance |
| `PATCH` | `/api/leave-balances/{id}/` | Change an allocation |
| `PUT` | `/api/leave-balances/{id}/` | Replace a leave balance |
| `GET` | `/api/leave/` | List leave requests |
| `POST` | `/api/leave/` | Not available to employers |
| `DELETE` | `/api/leave/{id}/` | Not available to employers |
| `GET` | `/api/leave/{id}/` | Retrieve one leave request |
| `PATCH` | `/api/leave/{id}/` | Approve or reject a leave request |
| `PUT` | `/api/leave/{id}/` | Decide a leave request |


### Employer · Holidays

**Authentication:** Bearer JWT &nbsp;&nbsp; **Role:** `employer`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/holidays/` | List company holidays |
| `POST` | `/api/holidays/` | Add a holiday |
| `DELETE` | `/api/holidays/{id}/` | Delete a holiday |
| `GET` | `/api/holidays/{id}/` | Retrieve one holiday |
| `PATCH` | `/api/holidays/{id}/` | Update a holiday |
| `PUT` | `/api/holidays/{id}/` | Replace a holiday |


### Employer · Announcements

**Authentication:** Bearer JWT &nbsp;&nbsp; **Role:** `employer`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/announcements/` | List announcements |
| `POST` | `/api/announcements/` | Publish an announcement |
| `DELETE` | `/api/announcements/{id}/` | Delete an announcement |
| `GET` | `/api/announcements/{id}/` | Retrieve one announcement |
| `PATCH` | `/api/announcements/{id}/` | Edit an announcement |
| `PUT` | `/api/announcements/{id}/` | Replace an announcement |


### Employer · Calendar

**Authentication:** Bearer JWT &nbsp;&nbsp; **Role:** `employer`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/calendar-events/` | List calendar events |
| `POST` | `/api/calendar-events/` | Create a calendar event |
| `DELETE` | `/api/calendar-events/{id}/` | Delete a calendar event |
| `GET` | `/api/calendar-events/{id}/` | Retrieve one calendar event |
| `PATCH` | `/api/calendar-events/{id}/` | Update a calendar event |
| `PUT` | `/api/calendar-events/{id}/` | Replace a calendar event |


### Employer · Payroll

**Authentication:** Bearer JWT &nbsp;&nbsp; **Role:** `employer`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/payroll/` | List payroll records |
| `POST` | `/api/payroll/` | Create a payroll record |
| `DELETE` | `/api/payroll/{id}/` | Delete a draft payroll record |
| `GET` | `/api/payroll/{id}/` | Retrieve one payroll record |
| `PATCH` | `/api/payroll/{id}/` | Update a draft payroll record |
| `PUT` | `/api/payroll/{id}/` | Replace a draft payroll record |
| `GET` | `/api/salaries/` | List monthly salaries |
| `POST` | `/api/salaries/` | Set an employee's salary |
| `DELETE` | `/api/salaries/{id}/` | Delete a salary |
| `GET` | `/api/salaries/{id}/` | Retrieve one salary |
| `PATCH` | `/api/salaries/{id}/` | Update a salary |
| `PUT` | `/api/salaries/{id}/` | Replace a salary |
| `POST` | `/api/salaries/{id}/mark_paid/` | Pay a month from the salary record |


### Employer · Reports

**Authentication:** Bearer JWT &nbsp;&nbsp; **Role:** `employer`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/reports/` | Manager dashboard report |


### Employee workspace

**Authentication:** Bearer JWT &nbsp;&nbsp; **Role:** `employee`, after contract approval

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/me/announcements/` | List announcements for you |
| `POST` | `/api/me/announcements/read-all/` | Mark every announcement as read |
| `POST` | `/api/me/announcements/{id}/read/` | Mark an announcement as read |
| `GET` | `/api/me/attendance/` | Read your clock state |
| `POST` | `/api/me/attendance/` | Clock in or out |
| `GET` | `/api/me/calendar/` | List calendar events for you |
| `POST` | `/api/me/calendar/read-all/` | Mark every calendar event as read |
| `POST` | `/api/me/calendar/{id}/read/` | Mark a calendar event as read |
| `GET` | `/api/me/contracts/` | List your contracts |
| `POST` | `/api/me/contracts/{id}/sign/` | Sign a contract |
| `POST` | `/api/me/contracts/{id}/termination/` | Ask to end your contract |
| `POST` | `/api/me/contracts/{id}/termination/acknowledge/` | Acknowledge an employer termination |
| `GET` | `/api/me/leave/` | Read your leave balances and requests |
| `POST` | `/api/me/leave/` | Request leave |
| `DELETE` | `/api/me/leave/{id}/` | Cancel your pending leave request |
| `PATCH` | `/api/me/leave/{id}/` | Change your pending leave request |
| `GET` | `/api/me/photo/` | Download your own profile photo |
| `GET` | `/api/me/profile/` | Read your own profile |
| `PATCH` | `/api/me/profile/` | Complete your own profile |

## Known limitations

- `GET /api/health/` is a plain Django view rather than a DRF one, so it is
  added to the schema by a documentation hook in `api/schema.py` instead of
  being introspected. Its real behaviour is in `backend/health.py`.
- Django's own admin (`/admin/`) and DRF's browsable-API login (`/api-auth/`)
  are HTML pages, not REST endpoints, and are deliberately outside the schema.
- File responses are documented as binary payloads; Swagger UI can call them but
  renders the bytes rather than previewing the file.
