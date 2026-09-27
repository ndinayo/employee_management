import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0014_contract_notification_sent_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="contract",
            name="employer_message",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="contract",
            name="revision_of",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="revisions", to="api.contract"),
        ),
    ]
