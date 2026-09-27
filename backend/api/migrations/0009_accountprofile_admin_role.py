from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0008_business_invite_email"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="accountprofile",
            name="account_role_matches_business",
        ),
        migrations.AlterField(
            model_name="accountprofile",
            name="role",
            field=models.CharField(choices=[
                ("employee", "Employee"), ("employer", "Employer"), ("admin", "Admin"),
            ], max_length=10),
        ),
        migrations.AddConstraint(
            model_name="accountprofile",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("business__isnull", True), ("role", "employee"))
                    | models.Q(("business__isnull", False), ("role", "employer"))
                    | models.Q(("business__isnull", True), ("role", "admin"))
                ),
                name="account_role_matches_business",
            ),
        ),
    ]
