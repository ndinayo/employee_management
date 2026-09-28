from decimal import Decimal

from django.db import migrations, models


def use_two_shifts(apps, schema_editor):
    Attendance = apps.get_model("api", "Attendance")
    Attendance.objects.filter(shift="morning").update(shift="day")
    Attendance.objects.filter(shift="afternoon").update(shift="evening")

    for night in Attendance.objects.filter(shift="night").order_by("id"):
        evening = Attendance.objects.filter(
            employee_id=night.employee_id,
            date=night.date,
            shift="evening",
        ).first()
        if evening is None:
            night.shift = "evening"
            night.save(update_fields=["shift"])
            continue

        evening.hours_worked = min(Decimal("24.00"), evening.hours_worked + night.hours_worked)
        check_ins = [value for value in (evening.check_in_at, night.check_in_at) if value]
        check_outs = [value for value in (evening.check_out_at, night.check_out_at) if value]
        evening.check_in_at = min(check_ins) if check_ins else None
        evening.check_out_at = max(check_outs) if check_outs else None
        evening.notes = "\n".join(value for value in (evening.notes, night.notes) if value)
        evening.save(update_fields=["hours_worked", "check_in_at", "check_out_at", "notes"])
        night.delete()


def restore_old_shift_names(apps, schema_editor):
    Attendance = apps.get_model("api", "Attendance")
    Attendance.objects.filter(shift="day").update(shift="morning")
    Attendance.objects.filter(shift="evening").update(shift="afternoon")


class Migration(migrations.Migration):
    dependencies = [("api", "0016_attendance_shift")]

    operations = [
        migrations.RunPython(use_two_shifts, restore_old_shift_names),
        migrations.AlterField(
            model_name="attendance",
            name="shift",
            field=models.CharField(
                choices=[("day", "Day"), ("evening", "Evening")],
                default="day",
                max_length=20,
            ),
        ),
    ]
