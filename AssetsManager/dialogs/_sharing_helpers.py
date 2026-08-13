"""Dialog-local translation and endpoint-state helpers extracted from the
sharing settings dialog.

Every symbol here was moved verbatim from ``sharing_settings_dialog.py``; the
dialog keeps thin delegates with the same names, so call sites and behavior are
unchanged.
"""
from AssetsManager.core import themes
from AssetsManager import i18n

tr = i18n.tr


def _msg(key: str, fallback: str) -> str:
    """Translate ``key`` with an English fallback while catalogs lack it.

    The i18n catalogs live outside this dialog's change scope; until the keys
    land there, missing entries resolve to ``fallback`` instead of the raw key.
    """
    from AssetsManager.i18n import _lookup
    try:
        if _lookup("en", key) is None:
            return fallback
    except Exception:
        return fallback
    return tr(key)


def _t():
    return themes.get()


def _endpoint_state(status: dict, tunnel_running: bool = False) -> str:
    """Map server facts to the small set of states rendered by the endpoint page."""
    state = status.get("state")
    if state in {"starting", "failed"}:
        return state
    if not status.get("running", False):
        return "off"
    return "public" if tunnel_running else "local"


def _endpoint_primary_action(state: str) -> str:
    """Return the action scope, leaving translated presentation to the widget."""
    return {
        "off": "start",
        "starting": "busy",
        "local": "stop_server",
        "public": "stop_tunnel",
        "failed": "retry",
    }.get(state, "start")
