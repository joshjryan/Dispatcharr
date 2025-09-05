from django.apps import AppConfig


class PluginsConfig(AppConfig):
    name = "apps.plugins"
    verbose_name = "Plugins"

    def ready(self):
        # Perform plugin discovery on startup
        try:
            from .loader import PluginManager

            PluginManager.get().discover_plugins()
        except Exception:
            # Avoid breaking startup due to plugin errors
            import logging

            logging.getLogger(__name__).exception("Plugin discovery failed during app ready")

