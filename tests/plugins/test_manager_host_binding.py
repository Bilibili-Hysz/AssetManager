"""Manager host-context binding lifecycle.

One PluginManagerService instance serves one PluginHostContext: parse_file(),
category and theme-token application all resolve through the bound
``_host_context``, so a second host would leave already-loaded records
pointing at the old one while lookups went to the new one.
"""

import json

import pytest

from AssetsManager.core.plugins.host_context import PluginHostContext
from AssetsManager.core.plugins.manager import PluginManagerService

PLUGIN_SRC = """
class Plugin:
    def register(self, host):
        host.show_notification("registered")

    def unregister(self, host):
        pass
"""


def _write_plugin(root, plugin_id):
    folder = root / plugin_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.json").write_text(
        json.dumps({
            "id": plugin_id,
            "name": plugin_id,
            "version": "1.0.0",
            "entry": "entry.py:Plugin",
            "kind": "python",
            "enabled": True,
            "permissions": [],
        }),
        encoding="utf-8",
    )
    (folder / "entry.py").write_text(PLUGIN_SRC, encoding="utf-8")
    return folder


@pytest.fixture
def manager(tmp_path):
    root = tmp_path / "plugins"
    root.mkdir()
    _write_plugin(root, "alpha")
    _write_plugin(root, "beta")
    service = PluginManagerService(search_paths=[root])
    service.discover_plugins()
    yield service
    PluginManagerService._instance = None


def test_second_host_context_is_refused(manager, caplog):
    first = PluginHostContext()
    second = PluginHostContext()
    assert manager.load_plugin("alpha", first).ok is True

    result = manager.load_plugin("beta", second)

    assert result.ok is False
    assert any(d.code == "plugin.host_context_conflict" for d in result.diagnostics)
    # The binding and the already-loaded record still point at the first host.
    assert manager._host_context is first
    assert manager._records["alpha"].host_context is first


def test_load_without_host_reuses_bound_context(manager):
    """A hostless load must not strip the record's registration path."""
    host = PluginHostContext()
    assert manager.load_plugin("alpha", host).ok is True

    result = manager.load_plugin("beta", None)

    assert result.ok is True
    assert manager._records["beta"].host_context is host
    # register() ran through the bound host, so the contribution landed there.
    assert any(n["message"] == "registered" for n in host.notifications())


def test_unload_releases_binding_when_last_plugin_goes(manager):
    host = PluginHostContext()
    manager.load_plugin("alpha", host)
    manager.load_plugin("beta", host)

    assert manager.unload_plugin("alpha") is True
    assert manager._host_context is host, "binding held while beta is loaded"

    assert manager.unload_plugin("beta") is True
    assert manager._host_context is None


def test_binding_released_then_rebindable(manager):
    first = PluginHostContext()
    manager.load_plugin("alpha", first)
    manager.unload_plugin("alpha")

    second = PluginHostContext()
    assert manager.load_plugin("alpha", second).ok is True
    assert manager._host_context is second


def test_unload_all_clears_every_plugin(manager):
    host = PluginHostContext()
    manager.load_plugin("alpha", host)
    manager.load_plugin("beta", host)

    assert manager.unload_all() is True

    assert all(r.plugin_instance is None for r in manager._records.values())
    assert manager._host_context is None
    # Idempotent: nothing loaded means nothing to do.
    assert manager.unload_all() is True
