from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0007_accountprofile_employee_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="business",
            name="email_host",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="business",
            name="email_host_password",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="business",
            name="email_host_user",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="business",
            name="email_port",
            field=models.PositiveIntegerField(default=587),
        ),
        migrations.AddField(
            model_name="business",
            name="email_use_tls",
            field=models.BooleanField(default=True),
        ),
    ]
