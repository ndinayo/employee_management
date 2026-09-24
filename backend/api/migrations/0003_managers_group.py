from django.db import migrations


def create_manager_group(apps, schema_editor):
    apps.get_model("auth", "Group").objects.using(schema_editor.connection.alias).get_or_create(name="Managers")


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0002_holiday_employee_address_employee_emergency_contact_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(create_manager_group, migrations.RunPython.noop)]
