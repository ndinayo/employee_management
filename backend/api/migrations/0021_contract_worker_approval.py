from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("api", "0020_contract_department_and_defaults")]

    operations = [
        migrations.AddField(
            model_name="contract",
            name="worker_approval_status",
            field=models.CharField(
                choices=[("pending", "Awaiting employer approval"), ("approved", "Approved to start work")],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="contract",
            name="worker_approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="contract",
            name="worker_approved_by",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
