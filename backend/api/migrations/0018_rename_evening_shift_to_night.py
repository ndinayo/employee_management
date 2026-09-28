from django.db import migrations, models


def use_night_shift(apps, schema_editor):
    Attendance = apps.get_model("api", "Attendance")
    Attendance.objects.filter(shift="evening").update(shift="night")


def restore_evening_shift(apps, schema_editor):
    Attendance = apps.get_model("api", "Attendance")
    Attendance.objects.filter(shift="night").update(shift="evening")


class Migration(migrations.Migration):
    dependencies = [("api", "0017_day_and_evening_shifts")]

    operations = [
        migrations.RunPython(use_night_shift, restore_evening_shift),
        migrations.AlterField(
            model_name="attendance",
            name="shift",
            field=models.CharField(
                choices=[("day", "Day"), ("night", "Night")],
                default="day",
                max_length=20,
            ),
        ),
    ]
