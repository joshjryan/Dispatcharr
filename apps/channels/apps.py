from django.apps import AppConfig

class ChannelsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.channels'
    verbose_name = "Channel & Stream Management"
    label = 'dispatcharr_channels'

    def ready(self):
        # Import signals so they get registered.
        import apps.channels.signals

        # Kick off DVR recovery shortly after startup (idempotent via Redis lock)
        try:
            from .tasks import recover_recordings_on_startup
            # Schedule with a short delay to allow migrations/DB readiness
            recover_recordings_on_startup.apply_async(countdown=5)
        except Exception:
            # Avoid hard failures at startup if Celery isn't ready yet
            pass
