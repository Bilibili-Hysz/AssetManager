"""Plugin loader — dynamic Python module loading."""
from __future__ import annotations

import importlib.util
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedPlugin:
    module: ModuleType
    entry_object: object
    plugin_instance: object


class _FunctionAdapter:
    """Wraps a module with match/parse functions as a plugin instance."""

    def __init__(self, module):
        self._module = module

    def match(self, file_path: str) -> bool:
        fn = getattr(self._module, "match", None)
        if fn is None:
            return False
        return bool(fn(file_path))

    def parse(self, file_path: str) -> dict:
        fn = getattr(self._module, "parse", None)
        if fn is None:
            return {}
        result = fn(file_path)
        return result if isinstance(result, dict) else {}

    def register(self, host):
        fn = getattr(self._module, "register", None)
        if fn:
            return fn(host)

    def unregister(self, host):
        fn = getattr(self._module, "unregister", None)
        if fn:
            return fn(host)


class _CallableAdapter:
    """Wraps a plain callable as a plugin with register/unregister."""

    def __init__(self, fn):
        self._fn = fn

    def register(self, host):
        return self._fn(host)

    def unregister(self, host):
        return None


class PluginLoader:
    def parse_entry(self, entry: str) -> tuple[str, str]:
        module_name, _, object_name = str(entry or "").partition(":")
        module_name = module_name.strip()
        object_name = object_name.strip()
        if not module_name:
            raise ValueError("Plugin entry must specify a module name.")
        # Strip .py extension if present (legacy plugin.json compatibility)
        if module_name.endswith(".py"):
            module_name = module_name[:-3]
        # Allow simple module name without :object for function-based plugins
        if not object_name:
            object_name = "__module__"
        return module_name, object_name

    def load(self, plugin_id: str, plugin_root: str | Path, entry: str) -> LoadedPlugin:
        module_name, object_name = self.parse_entry(entry)
        root_path = Path(plugin_root).resolve()
        module_path = (root_path / (module_name.replace(".", "/") + ".py")).resolve()
        if not module_path.exists():
            raise FileNotFoundError(f"Plugin module not found: {module_path}")
        if not module_path.is_relative_to(root_path):
            raise ValueError(f"Plugin entry escapes root directory: {entry}")

        runtime_name = f"_plugin_{plugin_id}_{module_name}".replace(".", "_")
        spec = importlib.util.spec_from_file_location(runtime_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Failed to create module spec for {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, object_name):
            # Support function-based plugins (match/parse in module)
            if hasattr(module, "match") and hasattr(module, "parse"):
                plugin_instance = self._build_instance(module, module=module)
                return LoadedPlugin(module=module, entry_object=module, plugin_instance=plugin_instance)
            raise AttributeError(f"Entry object '{object_name}' not found in '{module_name}'.")
        entry_object = getattr(module, object_name)
        plugin_instance = self._build_instance(entry_object, module=module)
        return LoadedPlugin(module=module, entry_object=entry_object, plugin_instance=plugin_instance)

    def _build_instance(self, entry_object: object, module: object = None) -> object:
        if inspect.isclass(entry_object):
            return entry_object()
        if hasattr(entry_object, "register") or hasattr(entry_object, "unregister"):
            return entry_object
        if callable(entry_object):
            return _CallableAdapter(entry_object)
        # Support function-based plugins (match/parse in module)
        if module is not None and hasattr(module, "match") and hasattr(module, "parse"):
            return _FunctionAdapter(module)
        raise TypeError("Plugin entry must be a class, callable, or object with register/unregister.")
