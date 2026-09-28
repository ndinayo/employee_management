from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("api", "0023_calendar_event_times")]

    operations = [
        migrations.CreateModel(
            name="CalendarEventRead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("read_at", models.DateTimeField(auto_now_add=True)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="calendar_event_reads", to="api.employee")),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reads", to="api.calendarevent")),
            ],
        ),
        migrations.AddConstraint(
            model_name="calendareventread",
            constraint=models.UniqueConstraint(fields=("event", "employee"), name="unique_employee_calendar_event_read"),
        ),
    ]
