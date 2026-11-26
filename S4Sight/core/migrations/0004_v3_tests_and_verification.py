"""v3: stool and STI tests (findings with several classes) and one-person verification with an expert queue."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0003_v2_phone_modality_confirmation")]

    operations = [
        migrations.AddField("detection", "label", models.CharField(default="afb", max_length=30)),
        migrations.AlterField("annotation", "label", models.CharField(default="afb", max_length=30)),
        migrations.AddField("slide", "findings", models.JSONField(blank=True, default=dict)),
        migrations.AddField("slide", "ai_findings", models.JSONField(blank=True, default=dict)),
        migrations.AddField("slide", "verification", models.CharField(blank=True, default="", max_length=10)),
        migrations.AddField("slide", "set_aside_by", models.CharField(blank=True, max_length=120, null=True)),
        migrations.AddField("slide", "set_aside_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("slide", "set_aside_reason", models.TextField(blank=True, null=True)),
        migrations.AddField("slide", "tech_result", models.CharField(blank=True, max_length=20, null=True)),
        migrations.AddField("slide", "tech_findings", models.JSONField(blank=True, default=dict)),
        migrations.AddField("slide", "expert_note", models.TextField(blank=True, null=True)),
    ]
