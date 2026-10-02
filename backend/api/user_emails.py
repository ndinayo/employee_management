"""One sign-in account per email address, compared case-insensitively.

New accounts are refused a used email by the application, and a partial unique
index on LOWER(email) enforces it in the database. Older databases can still
contain duplicates; those are reported, never merged or deleted, and the index is
added once they have been resolved. Blank emails are exempt.
"""
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Count
from django.db.models.functions import Lower

INDEX_NAME = "auth_user_email_ci_unique"


def _table():
    return get_user_model()._meta.db_table


def create_index_sql(table, quote):
    return (f"CREATE UNIQUE INDEX IF NOT EXISTS {quote(INDEX_NAME)} "
            f"ON {quote(table)} (LOWER({quote('email')})) WHERE {quote('email')} <> ''")


def drop_index_sql(quote):
    return f"DROP INDEX IF EXISTS {quote(INDEX_NAME)}"


def duplicate_email_groups(user_model=None):
    """{normalised email: [users sharing it, oldest first]} for every duplicated email."""
    User = user_model or get_user_model()
    emails = (User.objects.exclude(email="").annotate(normalized=Lower("email"))
              .values("normalized").annotate(total=Count("id")).filter(total__gt=1)
              .order_by("normalized").values_list("normalized", flat=True))
    return {email: list(User.objects.filter(email__iexact=email).order_by("pk")) for email in emails}


def unique_index_exists():
    with connection.cursor() as cursor:
        return INDEX_NAME in connection.introspection.get_constraints(cursor, _table())


def ensure_unique_index():
    """Add the index if no duplicates remain. Returns True when the index is in place."""
    if unique_index_exists():
        return True
    if duplicate_email_groups():
        return False
    with connection.cursor() as cursor:
        cursor.execute(create_index_sql(_table(), connection.ops.quote_name))
    return True


def drop_unique_index():
    with connection.cursor() as cursor:
        cursor.execute(drop_index_sql(connection.ops.quote_name))
