import datetime
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("api", "0022_announcements_and_calendar")]

    operations = [
        migrations.AddField(
            model_name="calendarevent",
            name="start_time",
            field=models.TimeField(default=datetime.time(9, 0)),
        ),
        migrations.AddField(
            model_name="calendarevent",
            name="end_time",
            field=models.TimeField(default=datetime.time(10, 0)),
        ),
    ]
