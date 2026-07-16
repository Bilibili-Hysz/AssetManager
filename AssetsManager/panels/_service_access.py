"""Presentation-layer accessors for scoped application services."""
from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger(__name__)


def _lookup_scoped_services(library_root: str | Path):
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return None, "no_qapplication"
        bootstrap = app.property("bootstrap")
        if bootstrap is None:
            return None, "missing_bootstrap"
        session = bootstrap.library_service.current_session
        if session is None or session.root != Path(library_root).resolve():
            return None, "session_not_open"
        return bootstrap.for_library(session), None
    except Exception:
        _log.debug("scoped service lookup failed for %s", library_root, exc_info=True)
        return None, "resolution_failed"


def get_scoped_services(library_root: str | Path):
    """Return library-scoped services from the QApplication bootstrap.

    This lives in the presentation layer because it depends on Qt application
    state (`QApplication.property("bootstrap")`).
    """
    scoped, reason = _lookup_scoped_services(library_root)
    if reason == "no_qapplication":
        _log.debug("scoped service lookup skipped: no QApplication instance")
    elif reason == "missing_bootstrap":
        _log.debug("scoped service lookup skipped: QApplication bootstrap property missing")
    return scoped


def require_scoped_services(library_root: str | Path, *, consumer: str = "presentation"):
    """Return scoped services or raise when they are unavailable."""
    scoped, reason = _lookup_scoped_services(library_root)
    if scoped is None:
        raise RuntimeError(
            f"{consumer} requires scoped library services for {library_root} ({reason or 'unknown'})"
        )
    return scoped
