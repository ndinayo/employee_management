"""The platform owner's dashboard: scale, lifecycle, usage, issues and health.

Everything here is about companies and the accounts that run them. A company's
own operational records (attendance, leave, payroll, contracts, salaries,
holidays, announcements) belong to its employer and are deliberately absent:
this module never reads them.

Every number is counted from live rows at request time. Nothing is cached,
stored or estimated.
"""
import platform
import shutil
import sys
import time
from datetime import timedelta

import django
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection
from django.db.models import Count, Max, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from . import onboarding
from .messaging import unread_for_admin
from .models import AccountProfile, Business, Employee, PlatformMessage
from .permissions import IsAdmin
from .schema import RESPONSE_403_ADMIN, with_errors

# A company nobody has signed into for this long is treated as dormant. Long
# enough that an ordinary quiet month does not trigger it.
DORMANT_DAYS = 60
# How many months of history the growth chart carries.
GROWTH_MONTHS = 12
# How many rows each "recent" list carries.
RECENT = 5
# Above this much disk in use, storage is reported as degraded rather than fine.
DISK_WARNING_PERCENT = 90


def admin_errors(success, **kwargs):
    return with_errors(success, forbidden=RESPONSE_403_ADMIN, **kwargs)


def as_when(value):
    if not value:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.isoformat()


def month_start(moment):
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def previous_month_start(moment):
    return month_start(month_start(moment) - timedelta(days=1))


def percent_change(now, before):
    """Growth against last month, as a whole percent.

    With nothing to compare against, any new company is reported as 100% rather
    than as an infinite jump.
    """
    if before:
        return round((now - before) / before * 100)
    return 100 if now else 0


def company_rows():
    """Every company with the counts and sign-in facts the dashboard needs.

    One pass, so a platform with hundreds of companies costs a handful of
    queries rather than a few per company.
    """
    employees = {
        row["business"]: (row["total"], row["active"])
        for row in Employee.objects.values("business").annotate(
            total=Count("id"), active=Count("id", filter=Q(is_active=True)))
    }
    failed = {
        row["business"]: row["failed"]
        for row in Employee.objects.filter(invite_email_failed=True).values("business").annotate(
            failed=Count("id"))
    }
    # A company may hold more than one employer sign-in, so take the most recent
    # sign-in across all of them as the company's own last activity.
    owners = {}
    for profile in AccountProfile.objects.filter(role="employer").select_related("user", "business"):
        current = owners.get(profile.business_id)
        user = profile.user
        if current is None or (user.last_login or timezone.now().replace(year=1970)) > (
                current["last_login_at"] or timezone.now().replace(year=1970)):
            owners[profile.business_id] = {
                "username": user.username, "email": user.email,
                "is_active": user.is_active, "last_login_at": user.last_login,
            }
    rows = []
    for business in Business.objects.order_by("-created_at", "-id"):
        owner = owners.get(business.pk)
        total, active = employees.get(business.pk, (0, 0))
        rows.append({
            "id": business.pk, "name": business.name, "status": business.status,
            "created_at": business.created_at,
            "status_changed_at": business.status_changed_at,
            "employer_username": owner["username"] if owner else "",
            "employer_email": owner["email"] if owner else "",
            "employer_is_active": bool(owner and owner["is_active"]),
            "last_login_at": owner["last_login_at"] if owner else None,
            "employee_count": total, "active_employee_count": active,
            "failed_invitations": failed.get(business.pk, 0),
        })
    return rows


def as_company(row, *, when=None):
    """A company as the dashboard lists it. Never any of its HR records."""
    return {
        "id": row["id"], "name": row["name"], "status": row["status"],
        "employer_username": row["employer_username"],
        "employee_count": row["employee_count"],
        "created_at": as_when(row["created_at"]),
        "last_login_at": as_when(row["last_login_at"]),
        "status_changed_at": as_when(row["status_changed_at"]),
        "when": as_when(when) if when else "",
    }


def growth_series(now):
    """Companies opened per month, oldest first, with a running total."""
    first = month_start(now)
    for _ in range(GROWTH_MONTHS - 1):
        first = previous_month_start(first)
    per_month = {}
    for business in Business.objects.filter(created_at__gte=first).values_list("created_at", flat=True):
        key = month_start(timezone.localtime(business) if timezone.is_aware(business) else business)
        stamp = (key.year, key.month)
        per_month[stamp] = per_month.get(stamp, 0) + 1
    running = Business.objects.filter(created_at__lt=first).count()
    series = []
    cursor = first
    while cursor <= month_start(now):
        added = per_month.get((cursor.year, cursor.month), 0)
        running += added
        series.append({
            "month": cursor.strftime("%Y-%m"),
            "label": cursor.strftime("%b"),
            "companies": added,
            "total": running,
        })
        # Step to the first of the next month without a calendar dependency.
        cursor = month_start(cursor + timedelta(days=32))
    return series


def recent_conversations(limit=RECENT):
    """The latest exchange with each company, newest first.

    Only dashboard messages: an emailed one went to an inbox and is its sender's
    own record, so it does not belong in a shared activity list.
    """
    newest = PlatformMessage.objects.filter(channel="message").values("business").annotate(
        last=Max("id"))
    messages = PlatformMessage.objects.filter(
        pk__in=[row["last"] for row in newest]).select_related("business").order_by("-created_at")[:limit]
    return [{
        "business": row.business_id, "business_name": row.business.name,
        "from_admin": row.from_admin, "body": row.body,
        "created_at": as_when(row.created_at),
        "awaiting_reply": not row.from_admin,
    } for row in messages]


def unresolved_requests():
    """Companies whose latest message is still waiting on the administrator.

    Derived from the conversation itself rather than a separate flag: a request
    is open until the administrator answers it.
    """
    newest = PlatformMessage.objects.filter(channel="message").values("business").annotate(
        last=Max("id"))
    return PlatformMessage.objects.filter(
        pk__in=[row["last"] for row in newest], from_admin=False).count()


def overview_data():
    now = timezone.now()
    rows = company_rows()
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=6)
    month = today - timedelta(days=29)
    this_month = month_start(timezone.localtime(now))
    last_month = previous_month_start(timezone.localtime(now))
    dormant_before = now - timedelta(days=DORMANT_DAYS)

    User = get_user_model()
    employers = User.objects.filter(account_profile__role="employer")
    signed_in = [row for row in rows if row["last_login_at"]]

    this_month_companies = sum(1 for row in rows if row["created_at"] >= this_month)
    last_month_companies = sum(1 for row in rows if last_month <= row["created_at"] < this_month)

    dormant_companies = [row for row in signed_in if row["last_login_at"] < dormant_before]
    never_used = [row for row in rows if not row["last_login_at"]]

    return {
        # 1. How big the platform is.
        "scale": {
            "companies": len(rows),
            "active_companies": sum(1 for row in rows if row["status"] == "active"),
            "pending_companies": sum(1 for row in rows if row["status"] == "pending"),
            "suspended_companies": sum(1 for row in rows if row["status"] == "suspended"),
            "employers": employers.count(),
            "employees": sum(row["employee_count"] for row in rows),
            "active_employees": sum(row["active_employee_count"] for row in rows),
            "companies_this_month": this_month_companies,
        },
        # 2. Where companies are in their life on the platform.
        "lifecycle": {
            "recent_registrations": [as_company(row, when=row["created_at"]) for row in rows[:RECENT]],
            "awaiting_activation": [as_company(row) for row in rows if row["status"] == "pending"][:RECENT],
            "recently_suspended": [
                as_company(row, when=row["status_changed_at"]) for row in sorted(
                    (row for row in rows if row["status"] == "suspended"),
                    key=lambda row: row["status_changed_at"] or row["created_at"], reverse=True)][:RECENT],
            "dormant": [as_company(row, when=row["last_login_at"]) for row in sorted(
                dormant_companies, key=lambda row: row["last_login_at"])][:RECENT],
            "dormant_days": DORMANT_DAYS,
        },
        # 3. How much the platform is actually being used.
        "usage": {
            "active_today": sum(1 for row in signed_in if row["last_login_at"] >= today),
            "active_week": sum(1 for row in signed_in if row["last_login_at"] >= week),
            "active_month": sum(1 for row in signed_in if row["last_login_at"] >= month),
            "total_users": User.objects.count(),
            "companies_this_month": this_month_companies,
            "companies_last_month": last_month_companies,
            "growth_percent": percent_change(this_month_companies, last_month_companies),
            "growth": growth_series(timezone.localtime(now)),
        },
        # 4. Accounts the administrator needs to do something about.
        "issues": {
            "dormant_employers": employers.filter(last_login__isnull=True, is_active=True).count(),
            "suspended_employers": employers.filter(is_active=False).count(),
            "disabled_accounts": User.objects.filter(is_active=False).count(),
            "companies_without_employer": sum(1 for row in rows if not row["employer_username"]),
            "failed_invitations": sum(row["failed_invitations"] for row in rows),
            "companies_with_failed_invitations": sum(1 for row in rows if row["failed_invitations"]),
            "email_delivery_configured": onboarding.can_deliver(),
            "never_used_companies": len(never_used),
        },
        # 5. What companies are asking for.
        "messages": {
            "unread": unread_for_admin(),
            "unresolved": unresolved_requests(),
            "recent": recent_conversations(),
        },
    }


# --- Health ------------------------------------------------------------------

def database_health():
    started = time.monotonic()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError as error:
        return {"status": "down", "detail": str(error)[:200],
                "engine": connection.vendor, "latency_ms": None}
    latency = round((time.monotonic() - started) * 1000, 1)
    return {
        "status": "operational" if latency < 500 else "degraded",
        "detail": f"Responded in {latency} ms.",
        "engine": connection.vendor,
        "latency_ms": latency,
    }


def email_health():
    if onboarding.platform_mail():
        return {"status": "operational", "detail": f"Sending through Brevo as {settings.DEFAULT_FROM_EMAIL}.",
                "sender": settings.DEFAULT_FROM_EMAIL, "host": "api.brevo.com"}
    sender = onboarding.shared_smtp()
    if sender:
        return {"status": "operational", "detail": f"Sending as {sender.email_host_user}.",
                "sender": sender.email_host_user, "host": sender.email_host or ""}
    if onboarding.can_deliver():
        return {"status": "operational", "detail": "Using the server's own mail settings.",
                "sender": settings.DEFAULT_FROM_EMAIL, "host": ""}
    return {"status": "not_configured",
            "detail": "No sender is set up, so invitations and emailed messages cannot go out.",
            "sender": "", "host": ""}


def storage_health():
    backend = settings.STORAGES["default"]["BACKEND"]
    if "S3" in backend:
        return {"status": "operational", "detail": "Files are stored in object storage.",
                "backend": "s3", "used_percent": None, "free_gb": None}
    try:
        usage = shutil.disk_usage(settings.MEDIA_ROOT if settings.MEDIA_ROOT.exists()
                                  else settings.BASE_DIR)
    except OSError as error:
        return {"status": "unknown", "detail": str(error)[:200],
                "backend": "filesystem", "used_percent": None, "free_gb": None}
    used_percent = round(usage.used / usage.total * 100, 1) if usage.total else 0
    free_gb = round(usage.free / 1024 ** 3, 1)
    return {
        "status": "degraded" if used_percent >= DISK_WARNING_PERCENT else "operational",
        "detail": f"{used_percent}% of the disk is in use, {free_gb} GB free.",
        "backend": "filesystem", "used_percent": used_percent, "free_gb": free_gb,
    }


def health_data():
    database = database_health()
    email = email_health()
    storage = storage_health()
    # The API answered this request, so it is up by definition; what it reports
    # is whether anything it depends on is not.
    degraded = [name for name, part in (("database", database), ("email", email), ("storage", storage))
                if part["status"] not in ("operational",)]
    return {
        "api": {
            "status": "operational" if not degraded else "degraded",
            "detail": "Serving requests." if not degraded
                      else "Serving requests, but " + ", ".join(degraded) + " needs attention.",
        },
        "database": database,
        "email": email,
        "storage": storage,
        "application": {
            "version": settings.SPECTACULAR_SETTINGS["VERSION"],
            "django": django.get_version(),
            "python": platform.python_version(),
            "environment": "development" if settings.DEBUG else "production",
            "debug": settings.DEBUG,
            "server_time": as_when(timezone.now()),
            "time_zone": settings.TIME_ZONE,
            "platform": f"{platform.system()} {platform.release()}",
            "runtime": sys.implementation.name,
        },
    }


# --- Documentation shapes ----------------------------------------------------

class CompanyRowSerializer(serializers.Serializer):
    """A company as the dashboard lists it. No HR records are ever included."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    status = serializers.ChoiceField(choices=Business.STATUSES)
    employer_username = serializers.CharField(allow_blank=True)
    employee_count = serializers.IntegerField()
    created_at = serializers.CharField(allow_blank=True)
    last_login_at = serializers.CharField(allow_blank=True)
    status_changed_at = serializers.CharField(allow_blank=True)
    when = serializers.CharField(allow_blank=True, help_text="The date this list is ordered by.")


class ScaleSerializer(serializers.Serializer):
    companies = serializers.IntegerField()
    active_companies = serializers.IntegerField()
    pending_companies = serializers.IntegerField()
    suspended_companies = serializers.IntegerField()
    employers = serializers.IntegerField()
    employees = serializers.IntegerField()
    active_employees = serializers.IntegerField()
    companies_this_month = serializers.IntegerField()


class LifecycleSerializer(serializers.Serializer):
    recent_registrations = CompanyRowSerializer(many=True)
    awaiting_activation = CompanyRowSerializer(many=True)
    recently_suspended = CompanyRowSerializer(many=True)
    dormant = CompanyRowSerializer(many=True)
    dormant_days = serializers.IntegerField()


class GrowthPointSerializer(serializers.Serializer):
    month = serializers.CharField()
    label = serializers.CharField()
    companies = serializers.IntegerField()
    total = serializers.IntegerField()


class UsageSerializer(serializers.Serializer):
    active_today = serializers.IntegerField(help_text="Companies whose employer signed in today.")
    active_week = serializers.IntegerField(help_text="Companies with a sign-in in the last 7 days.")
    active_month = serializers.IntegerField(
        help_text="Companies with a sign-in in the last 30 days. Rolling, not calendar, so "
                  "that today, this week and this month always nest.")
    total_users = serializers.IntegerField(help_text="Every account on the platform, all roles.")
    companies_this_month = serializers.IntegerField()
    companies_last_month = serializers.IntegerField()
    growth_percent = serializers.IntegerField()
    growth = GrowthPointSerializer(many=True)


class IssuesSerializer(serializers.Serializer):
    dormant_employers = serializers.IntegerField()
    suspended_employers = serializers.IntegerField()
    disabled_accounts = serializers.IntegerField()
    companies_without_employer = serializers.IntegerField()
    failed_invitations = serializers.IntegerField()
    companies_with_failed_invitations = serializers.IntegerField()
    email_delivery_configured = serializers.BooleanField()
    never_used_companies = serializers.IntegerField()


class ConversationRowSerializer(serializers.Serializer):
    business = serializers.IntegerField()
    business_name = serializers.CharField()
    from_admin = serializers.BooleanField()
    body = serializers.CharField()
    created_at = serializers.CharField()
    awaiting_reply = serializers.BooleanField()


class MessagesSerializer(serializers.Serializer):
    unread = serializers.IntegerField()
    unresolved = serializers.IntegerField(
        help_text="Companies whose latest message has not been answered yet.")
    recent = ConversationRowSerializer(many=True)


class PlatformOverviewSerializer(serializers.Serializer):
    """Everything the platform owner's dashboard shows, counted live."""

    scale = ScaleSerializer()
    lifecycle = LifecycleSerializer()
    usage = UsageSerializer()
    issues = IssuesSerializer()
    messages = MessagesSerializer()


class ServiceSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["operational", "degraded", "down", "not_configured", "unknown"])
    detail = serializers.CharField()


class HealthSerializer(serializers.Serializer):
    api = ServiceSerializer()
    database = ServiceSerializer()
    email = ServiceSerializer()
    storage = ServiceSerializer()
    application = serializers.DictField(help_text="Version and runtime information.")


@extend_schema(
    tags=["Platform administration"],
    summary="Platform overview",
    description="Everything the platform owner's dashboard shows, grouped into scale, "
                "lifecycle, usage, issues and messages. Every figure is counted from live "
                "rows when the request is served.\n\n"
                "A company's own operational records (attendance, leave, payroll, contracts, "
                "salaries, holidays, announcements) are never included: those belong to its "
                "employer, inside their own workspace.",
    responses=admin_errors({200: PlatformOverviewSerializer}, bad_request=False),
)
class AdminOverviewView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        return Response(overview_data())


@extend_schema(
    tags=["Platform administration"],
    summary="Platform health",
    description="The live state of the services the platform runs on. The database is "
                "pinged, email delivery is read from the configured sender, and disk use is "
                "measured on the file store. Nothing here is a fixed value.",
    responses=admin_errors({200: HealthSerializer}, bad_request=False),
)
class AdminHealthView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        return Response(health_data())
