"""Tests for ThemeLoader — scanning, validation, grouping, and hot-reload."""
import json

from AssetsManager.core.theme_loader import ThemeLoader


def _write_theme(path, name, *, dark=True, missing_tokens=None, valid=True):
    """Helper: write a minimal theme JSON file."""
    colors = {
        "base": "#1a1a1a", "panel": "#252525", "header": "#2d2d2d",
        "border": "#444444", "heading": "#e0e0e0", "body": "#c0c0c0",
        "muted": "#666666", "accent": "#4a60b0", "success": "#40b870",
        "warning": "#f5b040", "danger": "#f06060", "favorite": "#f0d060",
        "recent": "#70b8e0",
    }
    if missing_tokens:
        for token in missing_tokens:
            colors.pop(token, None)
    data = {"name": name, "dark": dark, "colors": colors}
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


# ── scan_directory / parse_theme ──────────────────────────────

def test_load_valid_themes(tmp_path):
    _write_theme(tmp_path / "D_navy.json", "Navy", dark=True)
    _write_theme(tmp_path / "D_slate.json", "Slate", dark=True)
    _write_theme(tmp_path / "L_dawn.json", "Dawn", dark=False)

    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()

    assert loader.get_theme("Navy") is not None
    assert loader.get_theme("Slate") is not None
    assert loader.get_theme("Dawn") is not None
    assert loader.get_theme("Bogus") is None


def test_skip_invalid_json(tmp_path):
    (tmp_path / "broken.json").write_text("{bad json", encoding="utf-8")
    _write_theme(tmp_path / "D_good.json", "Good")

    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()

    assert loader.get_theme("Good") is not None
    assert len(loader._themes) == 1


def test_skip_missing_required_tokens(tmp_path):
    _write_theme(tmp_path / "D_partial.json", "Partial", missing_tokens=["accent", "danger"])
    _write_theme(tmp_path / "D_complete.json", "Complete")

    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()

    assert loader.get_theme("Partial") is None
    assert loader.get_theme("Complete") is not None


def test_skip_non_dict_json(tmp_path):
    (tmp_path / "array.json").write_text('["not", "a", "dict"]', encoding="utf-8")
    _write_theme(tmp_path / "D_ok.json", "Ok")

    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()

    assert len(loader._themes) == 1


def test_skip_missing_name(tmp_path):
    colors = {
        "base": "#1a1a1a", "panel": "#252525", "header": "#2d2d2d",
        "border": "#444444", "heading": "#e0e0e0", "body": "#c0c0c0",
        "muted": "#666666", "accent": "#4a60b0", "success": "#40b870",
        "warning": "#f5b040", "danger": "#f06060", "favorite": "#f0d060",
        "recent": "#70b8e0",
    }
    (tmp_path / "noname.json").write_text(
        json.dumps({"colors": colors}), encoding="utf-8",
    )

    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()

    assert len(loader._themes) == 0


def test_missing_directory():
    loader = ThemeLoader(themes_dir="/nonexistent/path/themes")
    loader.scan_directory()
    assert len(loader._themes) == 0


def test_empty_directory(tmp_path):
    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()
    assert len(loader._themes) == 0


# ── validate_theme ────────────────────────────────────────────

def test_validate_valid_theme():
    data = {
        "name": "Test",
        "colors": {
            "base": "#000", "panel": "#111", "header": "#222",
            "border": "#333", "heading": "#444", "body": "#555",
            "muted": "#666", "accent": "#777", "success": "#888",
            "warning": "#999", "danger": "#aaa", "favorite": "#bbb",
            "recent": "#ccc",
        },
    }
    valid, errors = ThemeLoader.validate_theme(data)
    assert valid is True
    assert errors == []


def test_validate_missing_colors():
    valid, errors = ThemeLoader.validate_theme({"name": "Test"})
    assert valid is False
    assert any("colors" in e for e in errors)


def test_validate_missing_tokens():
    valid, errors = ThemeLoader.validate_theme({
        "name": "Test",
        "colors": {"base": "#000", "panel": "#111"},
    })
    assert valid is False
    assert len(errors) > 0


def test_validate_not_dict():
    valid, errors = ThemeLoader.validate_theme("not a dict")
    assert valid is False


# ── list_themes / grouping by prefix ──────────────────────────

def test_grouping_by_prefix(tmp_path):
    _write_theme(tmp_path / "D_navy.json", "Navy", dark=True)
    _write_theme(tmp_path / "D_slate.json", "Slate", dark=True)
    _write_theme(tmp_path / "L_dawn.json", "Dawn", dark=False)
    _write_theme(tmp_path / "U_custom.json", "Custom", dark=True)
    _write_theme(tmp_path / "other.json", "Other", dark=True)

    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()

    groups = loader.list_themes()

    assert "Dark" in groups
    assert "Light" in groups
    assert "User" in groups
    assert "Other" in groups

    dark_names = [t["name"] for t in groups["Dark"]]
    assert "Navy" in dark_names
    assert "Slate" in dark_names

    light_names = [t["name"] for t in groups["Light"]]
    assert "Dawn" in light_names

    user_names = [t["name"] for t in groups["User"]]
    assert "Custom" in user_names

    other_names = [t["name"] for t in groups["Other"]]
    assert "Other" in other_names


def test_empty_groups_excluded(tmp_path):
    _write_theme(tmp_path / "D_navy.json", "Navy")

    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()

    groups = loader.list_themes()
    assert "Dark" in groups
    assert "Light" not in groups
    assert "User" not in groups


# ── get_theme ─────────────────────────────────────────────────

def test_get_theme_returns_data(tmp_path):
    data = _write_theme(tmp_path / "D_navy.json", "Navy")

    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()

    result = loader.get_theme("Navy")
    assert result is not None
    assert result["name"] == "Navy"
    assert result["colors"]["accent"] == data["colors"]["accent"]


def test_get_theme_returns_none_for_missing(tmp_path):
    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()
    assert loader.get_theme("Nonexistent") is None


# ── reload_on_change (creating and deleting custom themes) ────

def test_create_custom_theme(tmp_path):
    _write_theme(tmp_path / "D_navy.json", "Navy")

    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()
    assert loader.get_theme("Custom") is None

    new_path = tmp_path / "U_custom.json"
    _write_theme(new_path, "Custom", dark=True)
    loader.reload_on_change(str(new_path))

    assert loader.get_theme("Custom") is not None


def test_delete_custom_theme(tmp_path):
    navy_path = tmp_path / "D_navy.json"
    _write_theme(navy_path, "Navy")

    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()
    assert loader.get_theme("Navy") is not None

    navy_path.unlink()
    loader.reload_on_change(str(navy_path))

    assert loader.get_theme("Navy") is None


def test_reload_on_change_emits_signal(tmp_path):
    path = tmp_path / "D_navy.json"
    _write_theme(path, "Navy")

    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()

    signals = []
    loader.themes_changed.connect(lambda: signals.append(True))

    _write_theme(path, "NavyUpdated")
    loader.reload_on_change(str(path))

    assert len(signals) == 1
    assert loader.get_theme("NavyUpdated") is not None


def test_reload_on_change_with_invalid_file(tmp_path):
    path = tmp_path / "D_navy.json"
    _write_theme(path, "Navy")

    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()

    path.write_text("{bad json", encoding="utf-8")
    loader.reload_on_change(str(path))

    assert loader.get_theme("Navy") is None


# ── parse_theme ───────────────────────────────────────────────

def test_parse_theme_valid(tmp_path):
    path = tmp_path / "theme.json"
    _write_theme(path, "Test")

    loader = ThemeLoader()
    data = loader.parse_theme(str(path))

    assert data is not None
    assert data["name"] == "Test"


def test_parse_theme_invalid(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")

    loader = ThemeLoader()
    assert loader.parse_theme(str(path)) is None


def test_parse_theme_nonexistent():
    loader = ThemeLoader()
    assert loader.parse_theme("/nonexistent/theme.json") is None
