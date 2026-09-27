from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("api", "0010_invitationemailsettings")]

    operations = [
        migrations.AddField(model_name="contract", name="content", field=models.TextField(blank=True)),
        migrations.AddField(model_name="contract", name="signature_status", field=models.CharField(
            choices=[("draft", "Draft"), ("sent", "Awaiting signature"), ("signed", "Signed")],
            default="draft", max_length=20)),
        migrations.AddField(model_name="contract", name="sent_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="contract", name="signed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="contract", name="signer_name", field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="contract", name="signature_data", field=models.TextField(blank=True)),
        migrations.AddField(model_name="contract", name="signed_ip", field=models.GenericIPAddressField(blank=True, null=True)),
        migrations.AddField(model_name="contract", name="content_hash", field=models.CharField(blank=True, max_length=64)),
    ]
