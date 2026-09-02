"""Tests for the single-file bundle resource checker."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = ROOT / "scripts" / "check_package_contents.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_package_contents", CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _complete_toc():
    """A TOC containing every resource the single-file contract requires."""
    return [
        "webui/dist/index.html",
        "webui/dist/assets/index-BEgCbF9d.js",
        "AssetsManager/i18n/en.json",
        "AssetsManager/i18n/zh.json",
        "AssetsManager/i18n/ja.json",
        "assets/icons/icon.ico",
        "Assets/Themes/D_Default.json",
        "Plugins/Addons/sample/plugin.json",
        "PySide6/QtSvg.pyd",
        "PySide6/QtOpenGL.pyd",
        "PySide6/QtOpenGLWidgets.pyd",
        "PySide6/Qt6Svg.dll",
        "PySide6/Qt6OpenGL.dll",
        "PySide6/Qt6OpenGLWidgets.dll",
    ]


def _without(entries, predicate):
    return [entry for entry in entries if not predicate(entry)]


# ── check_toc ──────────────────────────────────────────────────────────────

def test_check_toc_accepts_complete_bundle():
    assert _load_checker().check_toc(_complete_toc()) == []


def test_check_toc_normalizes_backslash_entries():
    module = _load_checker()
    entries = [entry.replace("/", "\\") for entry in _complete_toc()]
    assert module.check_toc(entries) == []


def test_check_toc_rejects_bundle_without_spa_index():
    module = _load_checker()
    missing = module.check_toc(
        _without(_complete_toc(), lambda e: e == "webui/dist/index.html")
    )
    assert "webui/dist/index.html" in missing


def test_check_toc_rejects_bundle_with_empty_spa_assets():
    module = _load_checker()
    missing = module.check_toc(
        _without(_complete_toc(), lambda e: e.startswith("webui/dist/assets/"))
    )
    assert "webui/dist/assets (no entries)" in missing


@pytest.mark.parametrize(
    "relative_path",
    (
        "AssetsManager/i18n/en.json",
        "AssetsManager/i18n/zh.json",
        "AssetsManager/i18n/ja.json",
        "assets/icons/icon.ico",
    ),
)
def test_check_toc_rejects_missing_stable_file(relative_path):
    module = _load_checker()
    missing = module.check_toc(_without(_complete_toc(), lambda e: e == relative_path))
    assert relative_path in missing


@pytest.mark.parametrize("prefix", ("Assets/Themes/", "Plugins/"))
def test_check_toc_rejects_empty_stable_directory(prefix):
    module = _load_checker()
    missing = module.check_toc(_without(_complete_toc(), lambda e: e.startswith(prefix)))
    assert f"{prefix.rstrip('/')} (no entries)" in missing


@pytest.mark.parametrize("module_name", ("QtSvg", "QtOpenGL", "QtOpenGLWidgets"))
def test_check_toc_rejects_missing_qt_module(module_name):
    module = _load_checker()
    missing = module.check_toc(
        _without(_complete_toc(), lambda e: e.startswith(f"PySide6/{module_name}."))
    )
    assert any(f"PySide6/{module_name}" in m for m in missing)


@pytest.mark.parametrize(
    "library_stem", ("Qt6Svg", "Qt6OpenGL", "Qt6OpenGLWidgets")
)
def test_check_toc_rejects_missing_qt_runtime_library(library_stem):
    module = _load_checker()
    missing = module.check_toc(
        _without(_complete_toc(), lambda e: e.startswith(f"PySide6/{library_stem}."))
    )
    assert any(f"PySide6/{library_stem}" in m for m in missing)


def test_check_toc_accepts_abi_suffixed_qt_module():
    """Extension binaries may carry an ABI suffix (QtSvg.cp314-win_amd64.pyd)."""
    module = _load_checker()
    entries = _complete_toc()
    entries = [e for e in entries if not e.startswith("PySide6/QtSvg.")]
    entries.append("PySide6/QtSvg.cp314-win_amd64.pyd")
    assert module.check_toc(entries) == []


# ── check_exe (PE + size; TOC stubbed) ─────────────────────────────────────

def test_check_exe_accepts_valid_pe(monkeypatch, tmp_path):
    module = _load_checker()
    exe = tmp_path / "AssetManager.exe"
    exe.write_bytes(b"MZ" + b"\x00" * 2048)
    monkeypatch.setattr(module, "_embedded_toc", lambda p: _complete_toc())
    assert module.check_exe(exe, min_size=2) == []


def test_check_exe_rejects_missing_file(tmp_path):
    module = _load_checker()
    problems = module.check_exe(tmp_path / "nope.exe")
    assert any("missing executable" in p for p in problems)


def test_check_exe_rejects_non_pe(monkeypatch, tmp_path):
    module = _load_checker()
    exe = tmp_path / "AssetManager.exe"
    exe.write_bytes(b"not-a-pe" + b"\x00" * 2048)
    monkeypatch.setattr(module, "_embedded_toc", lambda p: _complete_toc())
    problems = module.check_exe(exe, min_size=2)
    assert any("PE image" in p for p in problems)


def test_check_exe_rejects_undersized(monkeypatch, tmp_path):
    module = _load_checker()
    exe = tmp_path / "AssetManager.exe"
    exe.write_bytes(b"MZ" + b"\x00" * 16)
    monkeypatch.setattr(module, "_embedded_toc", lambda p: _complete_toc())
    problems = module.check_exe(exe, min_size=1024)
    assert any("below minimum" in p for p in problems)


def test_check_exe_skips_toc_when_pyinstaller_absent(monkeypatch, tmp_path):
    module = _load_checker()
    exe = tmp_path / "AssetManager.exe"
    exe.write_bytes(b"MZ" + b"\x00" * 2048)

    def _raise_import(p):
        raise ImportError("PyInstaller")

    monkeypatch.setattr(module, "_embedded_toc", _raise_import)
    assert module.check_exe(exe, min_size=2) == []


def test_check_exe_integrates_toc_missing(monkeypatch, tmp_path):
    module = _load_checker()
    exe = tmp_path / "AssetManager.exe"
    exe.write_bytes(b"MZ" + b"\x00" * 2048)
    monkeypatch.setattr(module, "_embedded_toc", lambda p: [])
    problems = module.check_exe(exe, min_size=2)
    assert "webui/dist/index.html" in problems


# ── check_spec (static drift) ──────────────────────────────────────────────

def _write_spec(root: Path, text: str) -> Path:
    spec = root / "AssetManager.spec"
    spec.write_text(text, encoding="utf-8")
    return spec


def test_check_spec_accepts_consistent_spec(tmp_path):
    module = _load_checker()
    (tmp_path / "AssetsManager" / "i18n").mkdir(parents=True)
    (tmp_path / "AssetsManager" / "i18n" / "en.json").touch()
    (tmp_path / "AssetsManager" / "lan").mkdir(parents=True)
    (tmp_path / "AssetsManager" / "lan" / "server.py").touch()
    spec = _write_spec(
        tmp_path,
        "datas=[str(_root / 'AssetsManager' / 'i18n' / 'en.json')]\n"
        "hiddenimports=['AssetsManager.lan.server']\n",
    )
    assert module.check_spec(spec) == []


def test_check_spec_flags_missing_datas_source(tmp_path):
    module = _load_checker()
    spec = _write_spec(tmp_path, "datas=[str(_root / 'Assets' / 'icons')]\n")
    problems = module.check_spec(spec)
    assert any("datas source missing" in p for p in problems)


def test_check_spec_ignores_generated_webui_dist(tmp_path):
    """webui/dist is a build output, not a repo source — never flagged here."""
    module = _load_checker()
    spec = _write_spec(tmp_path, "datas=[str(_root / 'webui' / 'dist')]\n")
    assert module.check_spec(spec) == []


def test_check_spec_flags_dead_hidden_import(tmp_path):
    module = _load_checker()
    spec = _write_spec(tmp_path, "hiddenimports=['AssetsManager.lan.nonexistent']\n")
    problems = module.check_spec(spec)
    assert any("hidden import not found" in p for p in problems)


def test_check_spec_ignores_third_party_hidden_imports(tmp_path):
    """Only AssetsManager.* hidden imports are resolved against the source tree."""
    module = _load_checker()
    spec = _write_spec(tmp_path, "hiddenimports=['sqlite3', 'aiohttp.web']\n")
    assert module.check_spec(spec) == []


def test_check_spec_accepts_repo_spec():
    """The committed spec must stay drift-free (the M3 dead-entry regression)."""
    assert _load_checker().check_spec(ROOT / "AssetManager.spec") == []
