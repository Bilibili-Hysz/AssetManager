"""Unit tests for scripts/build_installer.py — version injection + ISCC lookup."""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_installer  # noqa: E402


def test_read_app_version_matches_imported_constant():
    """The parsed single-source version equals the real constants.APP_VERSION."""
    from AssetsManager.core.constants import APP_VERSION

    assert build_installer.read_app_version() == APP_VERSION


def test_read_app_version_missing_constant_fails(tmp_path):
    constants = tmp_path / "constants.py"
    constants.write_text("OTHER = 1\n", encoding="utf-8")
    with pytest.raises(build_installer.BuildError, match="APP_VERSION"):
        build_installer.read_app_version(constants)


def test_write_version_include_stamps_define(tmp_path):
    include = tmp_path / "installer" / "_version.iss"
    result = build_installer.write_version_include("1.2.3", include)
    assert result == include
    assert '#define APP_VERSION "1.2.3"' in include.read_text(encoding="utf-8")


def test_locate_iscc_prefers_env_override(tmp_path):
    fake = tmp_path / "ISCC.exe"
    fake.write_text("", encoding="utf-8")
    assert build_installer.locate_iscc(
        env={"ISCC_PATH": str(fake)}, which=lambda name: None
    ) == fake


def test_locate_iscc_env_override_missing_file_raises(tmp_path):
    with pytest.raises(build_installer.BuildError, match="ISCC_PATH"):
        build_installer.locate_iscc(
            env={"ISCC_PATH": str(tmp_path / "nope.exe")},
            which=lambda name: None,
        )


def test_locate_iscc_falls_back_to_program_files(tmp_path):
    installed = tmp_path / "Inno Setup 6" / "ISCC.exe"
    installed.parent.mkdir(parents=True)
    installed.write_text("", encoding="utf-8")
    assert build_installer.locate_iscc(
        env={"PROGRAMFILES(X86)": str(tmp_path)}, which=lambda name: None
    ) == installed


def test_locate_iscc_path_lookup_last(tmp_path):
    found = tmp_path / "shim-ISCC.exe"
    assert build_installer.locate_iscc(
        env={}, which=lambda name: str(found) if "ISCC" in name.upper() else None
    ) == found


def test_locate_iscc_absent_raises():
    with pytest.raises(build_installer.BuildError, match="ISCC"):
        build_installer.locate_iscc(env={}, which=lambda name: None)


def test_validate_iss_accepts_repo_installer_script():
    assert build_installer.validate_iss() == []


def test_validate_iss_flags_missing_directive_and_include(tmp_path):
    iss = tmp_path / "broken.iss"
    iss.write_text("[Setup]\nAppId={{AAA}\n", encoding="utf-8")
    problems = build_installer.validate_iss(iss)
    assert any("PrivilegesRequired=lowest" in p for p in problems)
    assert any("DefaultDirName" in p for p in problems)
    assert any("_version.iss" in p for p in problems)


def test_main_dry_run_passes_without_inno(tmp_path, capsys):
    """--dry-run: version stamping + static check complete without ISCC."""
    exit_code = build_installer.main(
        ["--dry-run", "--version-include", str(tmp_path / "_version.iss")]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert (tmp_path / "_version.iss").is_file()
