from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0013_leave_management"),
    ]

    operations = [
        migrations.AddField(
            model_name="contract",
            name="notification_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
