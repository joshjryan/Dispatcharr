import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view
from apps.accounts.permissions import (
    Authenticated,
    permission_classes_by_method,
)

from .loader import PluginManager
from .models import PluginConfig

logger = logging.getLogger(__name__)


class PluginsListAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def get(self, request):
        pm = PluginManager.get()
        # Ensure registry is up-to-date on each request
        pm.discover_plugins()
        return Response({"plugins": pm.list_plugins()})


class PluginReloadAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def post(self, request):
        pm = PluginManager.get()
        pm.discover_plugins()
        return Response({"success": True, "count": len(pm._registry)})


class PluginSettingsAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def post(self, request, key):
        pm = PluginManager.get()
        data = request.data or {}
        settings = data.get("settings", {})
        try:
            updated = pm.update_settings(key, settings)
            return Response({"success": True, "settings": updated})
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PluginRunAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def post(self, request, key):
        pm = PluginManager.get()
        action = request.data.get("action")
        params = request.data.get("params", {})
        if not action:
            return Response({"success": False, "error": "Missing 'action'"}, status=status.HTTP_400_BAD_REQUEST)

        # Respect plugin enabled flag
        try:
            cfg = PluginConfig.objects.get(key=key)
            if not cfg.enabled:
                return Response({"success": False, "error": "Plugin is disabled"}, status=status.HTTP_403_FORBIDDEN)
        except PluginConfig.DoesNotExist:
            return Response({"success": False, "error": "Plugin not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            result = pm.run_action(key, action, params)
            return Response({"success": True, "result": result})
        except PermissionError as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            logger.exception("Plugin action failed")
            return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PluginEnabledAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def post(self, request, key):
        enabled = request.data.get("enabled")
        if enabled is None:
            return Response({"success": False, "error": "Missing 'enabled' boolean"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            cfg = PluginConfig.objects.get(key=key)
            cfg.enabled = bool(enabled)
            cfg.save(update_fields=["enabled", "updated_at"])
            return Response({"success": True, "enabled": cfg.enabled})
        except PluginConfig.DoesNotExist:
            return Response({"success": False, "error": "Plugin not found"}, status=status.HTTP_404_NOT_FOUND)
