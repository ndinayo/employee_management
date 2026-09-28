from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("api", "0018_rename_evening_shift_to_night")]

    operations = [
        migrations.AlterField(
            model_name="contract",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("active", "Active"),
                    ("ended", "Ended"),
                    ("terminated_mutual", "Terminated by Mutual Agreement"),
                ],
                default="active",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="ContractTerminationRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("initiated_by", models.CharField(choices=[("employee", "Employee"), ("employer", "Employer")], max_length=20)),
                ("reason", models.TextField()),
                ("proposed_last_working_date", models.DateField()),
                ("status", models.CharField(choices=[("pending", "Awaiting employer review"), ("awaiting_acknowledgement", "Awaiting employee acknowledgement"), ("approved", "Approved"), ("rejected", "Rejected"), ("acknowledged", "Acknowledged")], default="pending", max_length=30)),
                ("response_notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("contract", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="termination_requests", to="api.contract")),
            ],
        ),
    ]
