from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="PluginConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=128, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("version", models.CharField(blank=True, default="", max_length=64)),
                ("description", models.TextField(blank=True, default="")),
                ("enabled", models.BooleanField(default=False)),  # merged change
                ("ever_enabled", models.BooleanField(default=False)),  # merged addition
                ("settings", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        )
    ]
