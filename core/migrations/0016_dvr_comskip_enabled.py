from django.db import migrations
from django.utils.text import slugify


def add_comskip_setting(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")
    key = slugify("DVR Comskip Enabled")
    CoreSettings.objects.get_or_create(
        key=key,
        defaults={"name": "DVR Comskip Enabled", "value": "false"},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_dvr_templates"),
    ]

    operations = [
        migrations.RunPython(add_comskip_setting),
    ]

