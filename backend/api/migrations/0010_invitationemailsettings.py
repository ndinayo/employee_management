from django.db import migrations, models
import django.db.models.deletion


def copy_existing_sender(apps, schema_editor):
    Business = apps.get_model("api", "Business")
    InvitationEmailSettings = apps.get_model("api", "InvitationEmailSettings")
    source = Business.objects.exclude(email_host_user="").exclude(email_host_password="").order_by("id").first()
    if source:
        InvitationEmailSettings.objects.create(
            id=1,
            owner_business_id=source.id,
            email_host=source.email_host or "smtp.gmail.com",
            email_port=source.email_port or 587,
            email_use_tls=source.email_use_tls,
            email_host_user=source.email_host_user,
            email_host_password=source.email_host_password,
        )


class Migration(migrations.Migration):
    dependencies = [("api", "0009_accountprofile_admin_role")]

    operations = [
        migrations.CreateModel(
            name="InvitationEmailSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email_host", models.CharField(default="smtp.gmail.com", max_length=200)),
                ("email_port", models.PositiveIntegerField(default=587)),
                ("email_use_tls", models.BooleanField(default=True)),
                ("email_host_user", models.EmailField(blank=True, max_length=254)),
                ("email_host_password", models.CharField(blank=True, max_length=200)),
                ("owner_business", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="owned_invitation_email_settings", to="api.business",
                )),
            ],
        ),
        migrations.RunPython(copy_existing_sender, migrations.RunPython.noop),
    ]
