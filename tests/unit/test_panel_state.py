"""D2 PanelState contract tests."""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from AssetsManager.panels.panel_state import PanelState


def test_panel_state_persists_and_restores_owner_state(monkeypatch):
    settings = Mock()
    settings.get.return_value = {"depth": 4}
    monkeypatch.setattr(
        "AssetsManager.core.settings.AppSettings.instance",
        classmethod(lambda cls: settings),
    )

    class Owner:
        def save_state(self):
            return {"depth": 3}

        def restore_state(self, state):
            self.depth = state.get("depth")

    owner = Owner()
    state = PanelState("ui.test_state")
    state.persist(owner)

    settings.set.assert_called_once_with("ui.test_state", {"depth": 3})
    settings.save.assert_called_once()

    assert state.load(owner) is True
    assert owner.depth == 4


def test_panel_state_load_rejects_non_dict_state(monkeypatch):
    settings = Mock()
    settings.get.return_value = ["not", "a", "dict"]
    monkeypatch.setattr(
        "AssetsManager.core.settings.AppSettings.instance",
        classmethod(lambda cls: settings),
    )

    class Owner:
        def save_state(self):
            return {}

        def restore_state(self, state):
            raise AssertionError("restore must not run for invalid state")

    assert PanelState("ui.test_state").load(Owner()) is False


def test_panel_state_rejects_empty_key():
    with pytest.raises(ValueError):
        PanelState("")
    with pytest.raises(ValueError):
        PanelState(None)  # type: ignore[arg-type]


def test_info_and_sidebar_use_panel_state_keys():
    from AssetsManager.panels.info import InfoPanel
    from AssetsManager.panels.sidebar import SidebarPanel

    assert InfoPanel.panel_state_key == "info_panel_layout"
    assert SidebarPanel.panel_state_key == "sidebar_depth_cfg"
