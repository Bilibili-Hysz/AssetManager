"""Tests for the visual theme gallery dialog."""
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QFrame, QLineEdit, QPushButton

from AssetsManager.core import themes
from AssetsManager.widgets.theme_gallery import ThemeGalleryDialog


@pytest.fixture
def theme_api(monkeypatch):
    names = themes.names()[:4]
    data = {name: dict(themes.get(name)) for name in names}
    current = [names[0]]
    setter = Mock(side_effect=lambda name: current.__setitem__(0, name))
    monkeypatch.setattr(themes, "names", lambda: list(names))
    monkeypatch.setattr(themes, "get", lambda name=None: data[name or current[0]])
    monkeypatch.setattr(themes, "name", lambda: current[0])
    monkeypatch.setattr(themes, "set_theme", setter)
    return names, data, current, setter


@pytest.fixture
def gallery(theme_api):
    dialog = ThemeGalleryDialog()
    yield dialog
    dialog.close()


def test_creation_configures_gallery_dialog(gallery):
    assert gallery.isModal()
    assert gallery.windowTitle()
    assert gallery.size().width() >= 600
    assert gallery.size().height() >= 500
    assert "QDialog" in gallery.styleSheet()


def test_load_themes_populates_grid_without_duplicates(gallery, theme_api):
    names, _, _, _ = theme_api
    assert list(gallery._cards) == names
    assert gallery._grid_layout.count() == len(names)

    gallery._load_themes()

    assert list(gallery._cards) == names
    assert gallery._grid_layout.count() == len(names)


def test_create_theme_card_contains_swatches_and_widget_preview(gallery, theme_api):
    name = theme_api[0][0]
    card = gallery._cards[name]

    assert card.property("themeName") == name
    assert card.findChild(type(card), "ThemeCard") is None
    assert card.findChild(QLineEdit, "ThemeCardInput") is not None
    assert card.findChild(QPushButton, "ThemeCardButton") is not None
    assert card.findChild(QCheckBox, "ThemeCardCheck") is not None
    assert card.findChild(QFrame, "accentSwatch").property("color")
    assert card.findChild(QFrame, "baseSwatch").property("color")


def test_click_emits_selection_signal(gallery, theme_api):
    selected = []
    name = theme_api[0][1]
    gallery.theme_selected.connect(selected.append)

    QTest.mouseClick(gallery._cards[name], Qt.MouseButton.LeftButton)

    assert selected == [name]


def test_selection_applies_theme_and_marks_selected_card(gallery, theme_api):
    names, _, current, setter = theme_api
    selected = names[1]

    gallery._on_theme_clicked(selected)

    setter.assert_called_once_with(selected)
    assert current[0] == selected
    assert gallery._cards[selected].property("selected") is True
    assert gallery._cards[names[0]].property("selected") is False


def test_refresh_theme_rebuilds_stylekit_and_preserves_cards(gallery, theme_api):
    names, _, current, _ = theme_api
    previous_stylekit = gallery._sk
    current[0] = names[-1]

    gallery.refresh_theme()

    assert gallery._sk is not previous_stylekit
    assert list(gallery._cards) == names
    assert gallery._cards[names[-1]].property("selected") is True
    assert themes.get()["panel"] in gallery.styleSheet()
