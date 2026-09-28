from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("api", "0024_calendar_event_reads")]

    operations = [
        migrations.AddField(
            model_name="calendarevent",
            name="all_employees",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="calendarevent",
            name="invited_employees",
            field=models.ManyToManyField(blank=True, related_name="calendar_events", to="api.employee"),
        ),
    ]
