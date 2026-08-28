"""D4 gate tests — local QSS must not hardcode colors or font sizes."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = ROOT / "scripts" / "check_style_sources.py"
_spec = importlib.util.spec_from_file_location("check_style_sources", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_style_sources = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = check_style_sources
_spec.loader.exec_module(check_style_sources)


def test_style_source_gate_passes_on_current_tree() -> None:
    violations = check_style_sources.collect_violations(ROOT)
    assert violations == [], "\n".join(v.format() for v in violations)


def test_style_source_gate_covers_ui_surface() -> None:
    scoped = {p.name for p in check_style_sources._scoped_files(ROOT)}
    for expected in (
        "window.py",
        "window_coordinator.py",
        "dock_factory.py",
        "info.py",
        "startup.py",
        "plugin_manager_dialog.py",
        "stylekit.py",
    ):
        assert expected in scoped, expected


def test_stylekit_is_the_only_exempt_file() -> None:
    assert check_style_sources.EXEMPT_FILES == {
        "AssetsManager/widgets/stylekit.py"
    }


def test_literal_hex_in_qss_is_detected() -> None:
    violations: list = []
    check_style_sources._check_string(
        "QLabel { color: #ff0000; background: transparent; }",
        "panels/fake.py", 7, violations,
    )
    assert [v.rule for v in violations] == ["literal-hex-in-qss"]
    assert violations[0].line == 7


def test_literal_named_color_in_qss_is_detected() -> None:
    violations: list = []
    check_style_sources._check_string(
        "QLabel { color: white; }", "dialogs/fake.py", 3, violations)
    assert [v.rule for v in violations] == ["literal-named-color-in-qss"]


def test_raw_font_size_in_qss_is_detected() -> None:
    violations: list = []
    check_style_sources._check_string(
        "QLabel { font-size: 12px; }", "widgets/fake.py", 5, violations)
    assert [v.rule for v in violations] == ["literal-font-size-in-qss"]


def test_scaled_font_size_literal_in_fstring_is_detected() -> None:
    violations: list = []
    check_style_sources._check_string(
        "QLabel { font-size: {scaled_pt(11)}px; }", "widgets/fake.py", 9,
        violations,
    )
    assert [v.rule for v in violations] == ["literal-font-size-in-qss"]


def test_token_backed_font_size_is_allowed() -> None:
    violations: list = []
    check_style_sources._check_string(
        "QLabel { font-size: {scaled_pt(themes.font_size('caption'))}px; }",
        "widgets/fake.py", 11, violations,
    )
    assert violations == []


def test_interpolated_px_in_fstring_is_allowed() -> None:
    import ast

    source = 'x = f"padding: {scaled_px(10)}px {scaled_px(4)}px 0;"'
    node = ast.parse(source).body[0].value
    assert isinstance(node, ast.JoinedStr)
    violations: list = []
    check_style_sources._check_joined_str(
        node, source, "dialogs/fake.py", violations)
    assert violations == []


def test_literal_px_in_qss_is_detected() -> None:
    violations: list = []
    check_style_sources._check_string(
        "QLabel { padding: 10px 0 4px 12px; }", "dialogs/fake.py", 3, violations)
    assert [v.rule for v in violations] == ["literal-px-in-qss"] * 3
    assert {v.line for v in violations} == {3}
    # Literal px inside an f-string static part is flagged too.
    import ast

    source = 'x = f"padding: 10px 0 4px 12px;"'
    node = ast.parse(source).body[0].value
    assert isinstance(node, ast.JoinedStr)
    fstring_violations: list = []
    check_style_sources._check_joined_str(
        node, source, "dialogs/fake.py", fstring_violations)
    assert [v.rule for v in fstring_violations] == ["literal-px-in-qss"] * 3


def test_hex_fallback_next_to_theme_token_lookup_is_detected() -> None:
    violations: list = []
    check_style_sources._check_token_lookup_lines(
        ['color = t.get("danger", "#e74c3c")'], "dialogs/fake.py", violations)
    assert [v.rule for v in violations] == ["hex-fallback-in-theme-lookup"]


def test_font_size_fallback_maps_stay_in_sync() -> None:
    from AssetsManager.core import themes
    from AssetsManager.widgets.stylekit import _FONT_SIZE_FALLBACKS

    assert themes._FONT_SIZE_FALLBACKS == _FONT_SIZE_FALLBACKS


def test_dock_refresh_handlers_share_one_coalescing_slot() -> None:
    source = (ROOT / "AssetsManager" / "dock_factory.py").read_text(
        encoding="utf-8")
    assert "def _schedule_dock_refresh" in source
    assert "def _run_dock_refresh" in source
    assert source.count(".connect(_schedule_dock_refresh)") == 3
    assert "_refresh_docks_on_theme" not in source
    assert "_refresh_docks_on_language" not in source
    assert "_refresh_docks_on_scale" not in source
