import importlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from django.db import transaction

from .models import PluginConfig

logger = logging.getLogger(__name__)


@dataclass
class LoadedPlugin:
    key: str
    name: str
    version: str = ""
    description: str = ""
    module: Any = None
    instance: Any = None
    fields: List[Dict[str, Any]] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)


class PluginManager:
    """Singleton manager that discovers and runs plugins from /app/data/plugins."""

    _instance: Optional["PluginManager"] = None

    @classmethod
    def get(cls) -> "PluginManager":
        if not cls._instance:
            cls._instance = PluginManager()
        return cls._instance

    def __init__(self) -> None:
        self.plugins_dir = os.environ.get("DISPATCHARR_PLUGINS_DIR", "/app/data/plugins")
        self._registry: Dict[str, LoadedPlugin] = {}

        # Ensure plugins directory exists
        os.makedirs(self.plugins_dir, exist_ok=True)
        if self.plugins_dir not in sys.path:
            sys.path.append(self.plugins_dir)

    def discover_plugins(self) -> Dict[str, LoadedPlugin]:
        logger.info(f"Discovering plugins in {self.plugins_dir}")
        self._registry.clear()

        try:
            for entry in sorted(os.listdir(self.plugins_dir)):
                path = os.path.join(self.plugins_dir, entry)
                if not os.path.isdir(path):
                    continue

                plugin_key = entry.replace(" ", "_").lower()

                try:
                    self._load_plugin(plugin_key, path)
                except Exception:
                    logger.exception(f"Failed to load plugin '{plugin_key}' from {path}")

            logger.info(f"Discovered {len(self._registry)} plugin(s)")
        except FileNotFoundError:
            logger.warning(f"Plugins directory not found: {self.plugins_dir}")

        # Sync DB records
        self._sync_db_with_registry()
        return self._registry

    def _load_plugin(self, key: str, path: str):
        # Plugin can be a package or contain plugin.py
        module_name = None
        if os.path.exists(os.path.join(path, "__init__.py")):
            module_name = key
        elif os.path.exists(os.path.join(path, "plugin.py")):
            module_name = f"{key}.plugin"
        else:
            logger.debug(f"Skipping {path}: no plugin.py or package")
            return

        logger.debug(f"Importing plugin module {module_name}")
        module = importlib.import_module(module_name)

        # Expect a class named Plugin in the module
        plugin_cls = getattr(module, "Plugin", None)
        if plugin_cls is None:
            logger.warning(f"Module {module_name} has no Plugin class; skipping")
            return

        instance = plugin_cls()

        name = getattr(instance, "name", key)
        version = getattr(instance, "version", "")
        description = getattr(instance, "description", "")
        fields = getattr(instance, "fields", [])
        actions = getattr(instance, "actions", [])

        self._registry[key] = LoadedPlugin(
            key=key,
            name=name,
            version=version,
            description=description,
            module=module,
            instance=instance,
            fields=fields,
            actions=actions,
        )

    def _sync_db_with_registry(self):
        with transaction.atomic():
            for key, lp in self._registry.items():
                obj, _ = PluginConfig.objects.get_or_create(
                    key=key,
                    defaults={
                        "name": lp.name,
                        "version": lp.version,
                        "description": lp.description,
                        "settings": {},
                    },
                )
                # Update meta if changed
                changed = False
                if obj.name != lp.name:
                    obj.name = lp.name
                    changed = True
                if obj.version != lp.version:
                    obj.version = lp.version
                    changed = True
                if obj.description != lp.description:
                    obj.description = lp.description
                    changed = True
                if changed:
                    obj.save()

    def list_plugins(self) -> List[Dict[str, Any]]:
        from .models import PluginConfig

        plugins = []
        configs = {c.key: c for c in PluginConfig.objects.all()}
        for key, lp in self._registry.items():
            conf = configs.get(key)
            plugins.append(
                {
                    "key": key,
                    "name": lp.name,
                    "version": lp.version,
                    "description": lp.description,
                    "enabled": conf.enabled if conf else True,
                    "fields": lp.fields or [],
                    "settings": (conf.settings if conf else {}),
                    "actions": lp.actions or [],
                }
            )
        return plugins

    def get_plugin(self, key: str) -> Optional[LoadedPlugin]:
        return self._registry.get(key)

    def update_settings(self, key: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        cfg = PluginConfig.objects.get(key=key)
        cfg.settings = settings or {}
        cfg.save(update_fields=["settings", "updated_at"])
        return cfg.settings

    def run_action(self, key: str, action_id: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        lp = self.get_plugin(key)
        if not lp or not lp.instance:
            raise ValueError(f"Plugin '{key}' not found")

        cfg = PluginConfig.objects.get(key=key)
        if not cfg.enabled:
            raise PermissionError(f"Plugin '{key}' is disabled")
        params = params or {}

        # Provide a context object to the plugin
        context = {
            "settings": cfg.settings or {},
            "logger": logger,
            "actions": {a.get("id"): a for a in (lp.actions or [])},
        }

        # Run either via Celery if plugin provides a delayed method, or inline
        run_method = getattr(lp.instance, "run", None)
        if not callable(run_method):
            raise ValueError(f"Plugin '{key}' has no runnable 'run' method")

        try:
            result = run_method(action_id, params, context)
        except Exception:
            logger.exception(f"Plugin '{key}' action '{action_id}' failed")
            raise

        # Normalize return
        if isinstance(result, dict):
            return result
        return {"status": "ok", "result": result}
