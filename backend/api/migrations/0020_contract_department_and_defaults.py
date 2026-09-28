from django.db import migrations, models


def assign_departments(apps, schema_editor):
    Employee = apps.get_model("api", "Employee")
    Contract = apps.get_model("api", "Contract")
    for employee in Employee.objects.filter(department=""):
        title = employee.job_title.casefold()
        if "market" in title:
            department = "Marketing"
        elif "information" in title or title.strip() in {"it", "ict"}:
            department = "IT"
        elif "sale" in title:
            department = "Sales"
        elif "account" in title or "finance" in title:
            department = "Finance"
        elif "human resource" in title or title.strip() == "hr":
            department = "Human Resources"
        else:
            department = "Operations"
        employee.department = department
        employee.save(update_fields=["department"])
    for contract in Contract.objects.select_related("employee"):
        contract.department = contract.employee.department
        contract.save(update_fields=["department"])


class Migration(migrations.Migration):
    dependencies = [("api", "0019_contract_termination")]

    operations = [
        migrations.AddField(
            model_name="contract",
            name="department",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.RunPython(assign_departments, migrations.RunPython.noop),
    ]
