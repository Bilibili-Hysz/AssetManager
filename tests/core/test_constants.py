"""App identity constants — version is the single release source of truth."""
import re

from AssetsManager.core.constants import APP_VERSION


def test_app_version_exists_and_is_semverish():
    """APP_VERSION must exist and stay machine-parsable (major.minor.patch).

    The PyInstaller spec and the installer build script parse or consume this
    value verbatim, so a drift to a non semver-ish literal must fail loudly.
    """
    assert isinstance(APP_VERSION, str) and APP_VERSION
    assert re.fullmatch(r"\d+\.\d+\.\d+", APP_VERSION), APP_VERSION
