from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("api", "0021_contract_worker_approval")]

    operations = [
        migrations.CreateModel(
            name="Announcement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("message", models.TextField()),
                ("created_by", models.CharField(blank=True, max_length=200)),
                ("published_at", models.DateTimeField(auto_now_add=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="announcements", to="api.business")),
            ],
            options={"ordering": ["-published_at", "-id"]},
        ),
        migrations.CreateModel(
            name="CalendarEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("category", models.CharField(choices=[("holiday", "Holiday"), ("presentation", "Presentation"), ("meeting", "Meeting"), ("training", "Training"), ("other", "Other")], default="other", max_length=30)),
                ("date", models.DateField()),
                ("end_date", models.DateField(blank=True, null=True)),
                ("location", models.CharField(blank=True, max_length=250)),
                ("description", models.TextField(blank=True)),
                ("created_by", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="calendar_events", to="api.business")),
            ],
            options={"ordering": ["date", "id"]},
        ),
        migrations.CreateModel(
            name="AnnouncementRead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("read_at", models.DateTimeField(auto_now_add=True)),
                ("announcement", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reads", to="api.announcement")),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="announcement_reads", to="api.employee")),
            ],
        ),
        migrations.AddConstraint(
            model_name="announcementread",
            constraint=models.UniqueConstraint(fields=("announcement", "employee"), name="unique_employee_announcement_read"),
        ),
    ]
