"""Tool Scheduler — external tool launcher from JSON configuration.

Reads Shared/tools.json for tool definitions. Tools appear in
the Tools menu and file-list right-click "Open With" submenu.

Tool definition format:
[
  {"name": "Blender", "cmd": "blender.exe", "args": ["{file}"], "icon": ""},
  {"name": "VS Code", "cmd": "code.cmd", "args": ["{folder}"], "icon": ""}
]

Placeholders: {file} → selected file path, {folder} → current directory
"""
import json
import logging
import subprocess
import sys

from AssetsManager.core.database import SHARED_DIR

_log = logging.getLogger(__name__)

TOOLS_PATH = SHARED_DIR / "tools.json"

DEFAULT_TOOLS = [
    {"name": "Blender", "cmd": "blender", "args": ["{file}"], "icon": "cube"},
    {"name": "VS Code", "cmd": "code", "args": ["{folder}"], "icon": "code"},
]


def _load() -> list[dict]:
    """Load tools from JSON, falling back to defaults."""
    if not TOOLS_PATH.exists():
        _save(DEFAULT_TOOLS)
        return list(DEFAULT_TOOLS)
    try:
        data = json.loads(TOOLS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        _log.exception("Failed to load tools.json")
    return list(DEFAULT_TOOLS)


def _save(tools: list[dict]) -> None:
    TOOLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        TOOLS_PATH.write_text(
            json.dumps(tools, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        _log.exception("Failed to save tools.json")


def list_tools() -> list[dict]:
    """Return all configured tools."""
    return _load()


def run_tool(tool: dict, file_path: str = "", folder_path: str = "") -> None:
    """Execute a tool with substituted arguments."""
    cmd = tool.get("cmd", "")
    args = tool.get("args", [])
    if not cmd or not isinstance(cmd, str):
        raise ValueError('Invalid tool command')

    if file_path and '\x00' in str(file_path):
        raise ValueError('Invalid file path')
    if folder_path and '\x00' in str(folder_path):
        raise ValueError('Invalid folder path')

    resolved = []
    for a in args:
        a = a.replace("{file}", file_path or "")
        a = a.replace("{folder}", folder_path or "")
        resolved.append(a)

    full = [cmd] + resolved
    try:
        if sys.platform == "win32":
            subprocess.Popen(full, shell=False)
        else:
            subprocess.Popen(full, shell=False, start_new_session=True)
    except OSError:
        _log.exception("Failed to launch tool: %s", cmd)
