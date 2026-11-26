"""v3.2: a phone can hand a sample over to the computer once all photos are taken."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0004_v3_tests_and_verification")]

    operations = [
        migrations.AddField("slide", "photos_done_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("slide", "photos_done_by", models.CharField(blank=True, max_length=120, null=True)),
    ]
