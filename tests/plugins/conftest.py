"""Plugin test isolation fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_plugin_settings(isolated_plugin_settings):
    """Prevent plugin lifecycle tests from modifying user settings."""
