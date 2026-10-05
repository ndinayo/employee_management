from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured
import dj_database_url
import os
import sys

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
# Render mounts "Secret Files" here rather than in the project directory. Real
# environment variables always win over both files.
load_dotenv("/etc/secrets/.env")

def env_list(name, default=""):
    return [value.strip().rstrip("/") for value in os.getenv(name, default).split(",") if value.strip()]


def env_value(name, default=""):
    """A setting with surrounding whitespace and one pair of pasted quotes removed."""
    value = os.getenv(name, default).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1].strip()
    return value


ON_RENDER = os.getenv("RENDER", "").lower() == "true"
DEBUG = os.getenv("DEBUG", "false" if ON_RENDER else "true").lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set SECRET_KEY before starting with DEBUG=false.")
    SECRET_KEY = "django-insecure-local-development-only-employee-management"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
if render_hostname:
    ALLOWED_HOSTS.append(render_hostname)

# Invitation emails link here, so local development needs a working default.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173" if DEBUG else "").rstrip("/")
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", (
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"
    if DEBUG else ""
))
if FRONTEND_URL and FRONTEND_URL not in CORS_ALLOWED_ORIGINS:
    CORS_ALLOWED_ORIGINS.append(FRONTEND_URL)
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
if FRONTEND_URL:
    CSRF_TRUSTED_ORIGINS.append(FRONTEND_URL)
if render_hostname:
    CSRF_TRUSTED_ORIGINS.append(f"https://{render_hostname}")

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_SSL_HOST = render_hostname or None
if ON_RENDER:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Render can check readiness over internal HTTP without following a redirect.
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Documentation only. drf-spectacular reads the existing views, serializers
    # and permissions; it does not take part in handling requests.
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
}

# Password reset links are intentionally short-lived.
PASSWORD_RESET_TIMEOUT = 60 * 60

# --- OpenAPI / Swagger documentation -----------------------------------------
# Purely descriptive: it changes nothing about how requests are handled.
SPECTACULAR_SETTINGS = {
    "TITLE": "Employee Management API",
    "VERSION": "1.0.0",
    "DESCRIPTION": """
Interactive documentation for the Employee Management REST API.

### Roles

Every account has exactly one role, stored on its `AccountProfile`:

| Role | What it can reach |
| --- | --- |
| `admin` | the `/api/admin/...` platform endpoints: the dashboard, platform health, companies, employers, every employee, and messages from companies |
| `employer` | the employer workspace: employees, contracts, attendance, leave, holidays, announcements, calendar, salaries, payroll, reports, and `/api/messages/` to the platform team |
| `employee` | only the `/api/me/...` endpoints, and only once an employer has **approved their signed contract** |

A company also has a lifecycle of its own, held on its `Business` row and changed
only by the super admin: `pending` (signed up, not verified yet), `active`, and
`suspended` (its employer sign-ins are deactivated).

### Signing in from this page

1. `POST /api/token/` with `username` (a username **or** an email address) and `password`.
2. Copy the `access` value from the response.
3. Press **Authorize** at the top of this page and paste it into `jwtAuth`.
4. Protected operations now send `Authorization: Bearer <access>` for you.

Access tokens last 30 minutes; refresh them with `POST /api/token/refresh/`.
Accounts created by an employer come back with `must_change_password: true` and
must call `POST /api/account/password/` before anything else is useful.

### Errors

Validation failures return **400** with either `{"field": ["message", ...]}` or
`{"detail": "message"}`. Missing or expired credentials return **401**, a role
that is not allowed to use an endpoint returns **403**, and an unknown id
returns **404**.
""",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "SCHEMA_PATH_PREFIX": "/api",
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
    # Ship the UI from our own static files rather than a CDN.
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "SWAGGER_UI_SETTINGS": {
        # Deep linking makes Swagger UI write a "#/Tag" fragment into the address
        # bar as you browse. No address on this site carries a fragment.
        "deepLinking": False,
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "filter": True,
        "docExpansion": "none",
        "tryItOutEnabled": True,
    },
    "TAGS": [
        {"name": "Health", "description": "Unauthenticated readiness probe."},
        {"name": "Authentication", "description": "Sign up, obtain and refresh JWTs, and reset a forgotten password."},
        {"name": "Account", "description": "The signed-in account: who am I, my password, shared invitation email."},
        {"name": "Platform administration", "description": "Super admin only. The platform dashboard and health, companies and their lifecycle, employer accounts, every employee, and the conversations companies open with the platform team."},
        {"name": "Employer · Employees", "description": "Employer only. The employee register for the employer's own business."},
        {"name": "Employer · Contracts", "description": "Employer only. Draft, send, approve and terminate employment contracts."},
        {"name": "Employer · Attendance", "description": "Employer only. Attendance records the employer enters or corrects."},
        {"name": "Employer · Leave", "description": "Employer only. Approve or reject leave, and set yearly leave allocations."},
        {"name": "Employer · Holidays", "description": "Employer only. Company holidays, which are excluded from leave day counts."},
        {"name": "Employer · Announcements", "description": "Employer only. Announcements broadcast to the whole business."},
        {"name": "Employer · Calendar", "description": "Employer only. Company calendar events, for everyone or named invitees."},
        {"name": "Employer · Payroll", "description": "Employer only. Monthly salaries and payroll / payslip records."},
        {"name": "Employer · Reports", "description": "Employer only. The manager dashboard roll-up for one date."},
        {"name": "Employer · Messages", "description": "Employer only. This company's own conversation with the platform team."},
        {"name": "Employee workspace", "description": "Employee only, and only after the employer approves the signed contract."},
    ],
    # Several models call a field "status", so name those enums explicitly.
    "ENUM_NAME_OVERRIDES": {
        "ContractStatusEnum": "api.schema.CONTRACT_STATUS_CHOICES",
        "LeaveStatusEnum": "api.schema.LEAVE_STATUS_CHOICES",
        "CompanyStatusEnum": "api.schema.COMPANY_STATUS_CHOICES",
    },
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        # Adds /api/health/, which is a plain Django view and therefore invisible
        # to the DRF-based generator.
        "api.schema.add_non_drf_paths",
    ],
}


# Application definition

INSTALLED_APPS = [
    "jazzmin",
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    "api",
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    # Serves the Swagger UI / ReDoc bundles from this project's static files so
    # the docs page works without reaching out to a CDN.
    "drf_spectacular_sidecar",
]

JAZZMIN_SETTINGS = {
    "site_title": "Admin Dashboard",
    "site_header": "Admin Dashboard",
    "site_brand": "Admin Dashboard",
    "welcome_sign": "Admin Dashboard",
}

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {"default": dj_database_url.parse(
    os.environ["DATABASE_URL"], conn_max_age=600, conn_health_checks=True,
)} if os.getenv("DATABASE_URL") else {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["DB_NAME"],
        "USER": os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST": os.environ["DB_HOST"],
        "PORT": os.environ["DB_PORT"],
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = os.getenv("TIME_ZONE", "Africa/Johannesburg")

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Files are always read through the manager-only API, regardless of storage.
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", str(BASE_DIR / "private_media")))
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "filesystem")
if STORAGE_BACKEND == "s3":
    bucket = os.getenv("AWS_STORAGE_BUCKET_NAME", "")
    if not bucket:
        raise ImproperlyConfigured("Set AWS_STORAGE_BUCKET_NAME when STORAGE_BACKEND=s3.")
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": bucket,
            "access_key": os.getenv("AWS_ACCESS_KEY_ID"),
            "secret_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
            "region_name": os.getenv("AWS_S3_REGION_NAME", "us-east-1"),
            "endpoint_url": os.getenv("AWS_S3_ENDPOINT_URL") or None,
            "default_acl": None,
            "querystring_auth": True,
            "file_overwrite": False,
            "max_memory_size": 5 * 1024 * 1024,
        },
    }
elif STORAGE_BACKEND != "filesystem":
    raise ImproperlyConfigured("STORAGE_BACKEND must be filesystem or s3.")

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CORS_ALLOW_ALL_ORIGINS = False

# Outgoing mail. With no SMTP host configured, invitations are printed to the
# server console instead of being sent, so local development needs no account.
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() == "true"
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "false").lower() == "true"
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))
DEFAULT_FROM_EMAIL = env_value("DEFAULT_FROM_EMAIL") or EMAIL_HOST_USER or "no-reply@employee-management.local"
# Brevo sends over HTTPS, for hosts that block outbound SMTP. DEFAULT_FROM_EMAIL
# must be a sender verified in the Brevo account. The test suite never sees a real
# key from .env, so it cannot send live email; tests opt in with override_settings.
RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == "test"
BREVO_API_KEY = "" if RUNNING_TESTS else env_value("BREVO_API_KEY")
if BREVO_API_KEY:
    EMAIL_BACKEND = "api.brevo.BrevoEmailBackend"
elif EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Without EMAIL_HOST the console backend "succeeds" without delivering anything,
# so nothing may claim an invitation reached the employee.
EMAIL_DELIVERS = bool(EMAIL_HOST or BREVO_API_KEY)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"api": {"handlers": ["console"], "level": os.getenv("API_LOG_LEVEL", "INFO")}},
}
