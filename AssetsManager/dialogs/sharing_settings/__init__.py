"""Per-page mixins for the sharing settings dialog.

Each page's construction and visual helpers live in a dedicated mixin so the
main ``sharing_settings_dialog.py`` module keeps only the shell and the
settings/data/action logic.  Re-exported here for a single import site.
"""
from AssetsManager.dialogs.sharing_settings._ui import SharedUiMixin
from AssetsManager.dialogs.sharing_settings._endpoint_page import EndpointPageMixin
from AssetsManager.dialogs.sharing_settings._links_page import LinksPageMixin
from AssetsManager.dialogs.sharing_settings._access_page import AccessPageMixin
from AssetsManager.dialogs.sharing_settings._configuration_page import ConfigurationPageMixin

__all__ = [
    "SharedUiMixin",
    "EndpointPageMixin",
    "LinksPageMixin",
    "AccessPageMixin",
    "ConfigurationPageMixin",
]
