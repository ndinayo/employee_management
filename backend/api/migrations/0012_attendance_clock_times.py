from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("api", "0011_contract_digital_signing")]

    operations = [
        migrations.AddField(
            model_name="attendance", name="check_in_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="attendance", name="check_out_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
