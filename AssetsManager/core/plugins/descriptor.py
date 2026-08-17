"""Plugin descriptor — data models and manifest parsing."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

PLUGIN_STATE_DISCOVERED = "discovered"
PLUGIN_STATE_INVALID = "invalid"
PLUGIN_STATE_DISABLED = "disabled"
PLUGIN_STATE_LOADABLE = "loadable"
PLUGIN_STATE_LOADED = "loaded"
PLUGIN_STATE_ACTIVE = "active"
PLUGIN_STATE_ERROR = "error"

REQUIRED_MANIFEST_FIELDS = ("id", "name", "version")

# ── Plugin permission constants ──────────────────────────────────
#
# The host gates its own APIs on these tokens (resolved per plugin id by
# PluginHostContext).  What each token gates, and what a gate can and
# cannot do:
#
#   host.services  current_services() / current_session() /
#                  current_window().  Enforced boundary: the service
#                  bundle and the library session are reachable only
#                  through the host API.  The session reaches the
#                  database, so database access is bundled into this
#                  token.
#   settings.write register_category() / register_theme_token().
#                  Enforced boundary: these mutate global host
#                  registries reachable only through the host API.
#   filesystem.read  register_file_handler() / register_search_provider()
#                  / open_path().  Advisory: a plugin can read any file
#                  with the standard library, so the gate documents
#                  intent and catches honest mistakes; it does not
#                  contain filesystem access.
#   settings.read / settings.write  preferences() (the plugin's own bag,
#                  either token suffices).  Advisory for the same reason:
#                  a plugin can import the preferences module directly.
#
# Declared-only tokens — no host code checks them because the host
# exposes no API for the capability: filesystem.write, network.request,
# clipboard.read, clipboard.write.  The host performs no filesystem
# writes, network requests or clipboard access on a plugin's behalf, so
# there is nothing to gate; a plugin reaches those capabilities with the
# standard library directly.
#
# Fundamental caveat: plugins run in the same interpreter, unsandboxed.
# Every gate above — including host.services — can be bypassed by
# importing stdlib or host modules directly.  The gates are honesty and
# intent boundaries, not a security sandbox.

PERMISSION_FILESYSTEM_READ = "filesystem.read"
PERMISSION_FILESYSTEM_WRITE = "filesystem.write"
PERMISSION_NETWORK_REQUEST = "network.request"
PERMISSION_DATABASE_READ = "database.read"
PERMISSION_DATABASE_WRITE = "database.write"
PERMISSION_SETTINGS_READ = "settings.read"
PERMISSION_SETTINGS_WRITE = "settings.write"
PERMISSION_CLIPBOARD_READ = "clipboard.read"
PERMISSION_CLIPBOARD_WRITE = "clipboard.write"
PERMISSION_HOST_SERVICES = "host.services"

ALL_PERMISSIONS = frozenset({
    PERMISSION_FILESYSTEM_READ,
    PERMISSION_FILESYSTEM_WRITE,
    PERMISSION_NETWORK_REQUEST,
    PERMISSION_DATABASE_READ,
    PERMISSION_DATABASE_WRITE,
    PERMISSION_SETTINGS_READ,
    PERMISSION_SETTINGS_WRITE,
    PERMISSION_CLIPBOARD_READ,
    PERMISSION_CLIPBOARD_WRITE,
    PERMISSION_HOST_SERVICES,
})


@dataclass(frozen=True)
class DisplayField:
    """A field to render in the InfoPanel metadata section."""
    key: str
    label_key: str
    type: str = "text"


@dataclass(frozen=True)
class PluginDiagnostic:
    level: str
    code: str
    message: str
    plugin_id: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class PluginDescriptor:
    id: str
    name: str
    version: str
    entry: str = ""
    description: str | None = None
    kind: str = "command"
    enabled_by_default: bool = True
    manifest_path: str = ""
    root_dir: str = ""
    display_fields: tuple[DisplayField, ...] = ()
    permissions: frozenset[str] = frozenset()


@dataclass
class PluginRecord:
    plugin_id: str
    root_dir: str
    manifest_path: str
    manifest: dict[str, Any] | None = None
    descriptor: PluginDescriptor | None = None
    state: str = PLUGIN_STATE_DISCOVERED
    enabled: bool = True
    diagnostics: list[PluginDiagnostic] = field(default_factory=list)
    module: object | None = None
    plugin_instance: object | None = None
    host_context: object | None = None


@dataclass(frozen=True)
class PluginLoadResult:
    ok: bool
    plugin_id: str
    state: str
    diagnostics: tuple[PluginDiagnostic, ...] = ()


def load_manifest(manifest_path: str | Path) -> tuple[dict[str, Any] | None, list[PluginDiagnostic]]:
    path = Path(manifest_path)
    source = str(path)
    if not path.exists():
        return None, [PluginDiagnostic("error", "manifest.missing", "plugin.json not found.", source=source)]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [PluginDiagnostic("error", "manifest.invalid_json", f"Invalid JSON: {exc}", source=source)]
    except OSError as exc:
        return None, [PluginDiagnostic("error", "manifest.read_failed", f"Read failed: {exc}", source=source)]
    if not isinstance(payload, dict):
        return None, [PluginDiagnostic("error", "manifest.not_object", "Root must be an object.", source=source)]
    return payload, []


def parse_plugin_descriptor(
    manifest: dict[str, Any],
    *,
    manifest_path: str | Path,
) -> tuple[PluginDescriptor | None, list[PluginDiagnostic]]:
    source = str(manifest_path)
    diagnostics: list[PluginDiagnostic] = []
    plugin_id = str(manifest.get("id") or "").strip()

    for field_name in REQUIRED_MANIFEST_FIELDS:
        value = manifest.get(field_name)
        if not isinstance(value, str) or not value.strip():
            diagnostics.append(PluginDiagnostic(
                "error", "manifest.required_field_missing",
                f"Required field '{field_name}' is missing or empty.",
                plugin_id=plugin_id or None, source=source,
            ))

    if any(d.level == "error" for d in diagnostics):
        return None, diagnostics

    descriptor = PluginDescriptor(
        id=plugin_id,
        name=str(manifest.get("name") or "").strip(),
        version=str(manifest.get("version") or "").strip(),
        entry=str(manifest.get("entry") or "parser.py").strip(),
        description=str(manifest.get("description") or "").strip() or None,
        kind=str(manifest.get("kind") or "command").strip(),
        enabled_by_default=bool(manifest.get("enabled_by_default", manifest.get("enabled", True))),
        manifest_path=str(manifest_path),
        root_dir=str(Path(manifest_path).parent),
        display_fields=tuple(
            DisplayField(
                key=str(field.get("key", "")),
                label_key=str(field.get("label_key", field.get("key", ""))),
                type=str(field.get("type", "text")),
            )
            for field in (manifest.get("display_fields") or [])
            if isinstance(field, dict) and field.get("key")
        ),
        permissions=frozenset(
            str(p).strip()
            for p in (manifest.get("permissions") or [])
            if isinstance(p, str) and p.strip()
        ),
    )
    return descriptor, diagnostics


def build_plugin_record(
    manifest_path: str | Path,
) -> PluginRecord:
    path = Path(manifest_path)
    manifest, diagnostics = load_manifest(path)
    record = PluginRecord(
        plugin_id=path.parent.name,
        root_dir=str(path.parent),
        manifest_path=str(path),
        manifest=manifest,
        state=PLUGIN_STATE_DISCOVERED,
        enabled=True,
        diagnostics=list(diagnostics),
    )
    if manifest is None:
        record.state = PLUGIN_STATE_INVALID
        record.enabled = False
        return record

    descriptor, parse_diag = parse_plugin_descriptor(manifest, manifest_path=path)
    record.diagnostics.extend(parse_diag)
    if descriptor is None:
        record.state = PLUGIN_STATE_INVALID
        record.enabled = False
        return record

    record.plugin_id = descriptor.id
    record.descriptor = descriptor
    record.enabled = bool(descriptor.enabled_by_default)
    record.state = PLUGIN_STATE_LOADABLE if record.enabled else PLUGIN_STATE_DISABLED
    return record
