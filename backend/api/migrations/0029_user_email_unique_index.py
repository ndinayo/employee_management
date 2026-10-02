from django.db import migrations
from django.db.models import Count
from django.db.models.functions import Lower

INDEX_NAME = "auth_user_email_ci_unique"


def add_unique_email_index(apps, schema_editor):
    User = apps.get_model("auth", "User")
    duplicates = (User.objects.using(schema_editor.connection.alias).exclude(email="")
                  .annotate(normalized=Lower("email")).values("normalized")
                  .annotate(total=Count("id")).filter(total__gt=1).count())
    if duplicates:
        # Existing accounts are never merged or deleted here. `check_duplicate_emails`
        # lists them on every start and adds the index once they are resolved.
        print(f"\n  Skipped {INDEX_NAME}: {duplicates} email address(es) are shared by several accounts. "
              "Run `python manage.py check_duplicate_emails` for details.")
        return
    quote = schema_editor.quote_name
    schema_editor.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {quote(INDEX_NAME)} "
        f"ON {quote(User._meta.db_table)} (LOWER({quote('email')})) WHERE {quote('email')} <> ''")


def remove_unique_email_index(apps, schema_editor):
    schema_editor.execute(f"DROP INDEX IF EXISTS {schema_editor.quote_name(INDEX_NAME)}")


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0028_business_status_business_status_changed_at_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(add_unique_email_index, remove_unique_email_index)]
