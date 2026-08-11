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
import os
import subprocess
import sys
import tempfile

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
    """Atomically write tools.json via tempfile + os.replace."""
    tmp = None
    try:
        TOOLS_PATH.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(tools, indent=2, ensure_ascii=False)
        fd, tmp = tempfile.mkstemp(dir=str(TOOLS_PATH.parent),
                                   suffix=".tmp", prefix="tools_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(TOOLS_PATH))
    except (OSError, TypeError, ValueError):
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass
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
    name = tool.get("name") or cmd
    if not isinstance(args, list) or not all(
            isinstance(a, (str, int, float)) and not isinstance(a, bool)
            for a in args):
        raise ValueError(f'Invalid tool args for "{name}"')

    if file_path and '\x00' in str(file_path):
        raise ValueError('Invalid file path')
    if folder_path and '\x00' in str(folder_path):
        raise ValueError('Invalid folder path')

    resolved = []
    for a in args:
        a = str(a)
        a = a.replace("{file}", file_path or "")
        a = a.replace("{folder}", folder_path or "")
        resolved.append(a)

    full = [cmd] + resolved
    try:
        if sys.platform == "win32":
            # Windows' CreateProcess cannot execute .cmd/.bat directly
            # (WinError 193); wrap them in cmd.exe.
            subprocess.Popen(_windows_launch_command(full), shell=False)
        else:
            subprocess.Popen(full, shell=False, start_new_session=True)
    except OSError:
        _log.exception("Failed to launch tool: %s", cmd)


def _windows_launch_command(full: list[str]) -> list[str]:
    """Return a launchable command for Windows batch files.

    ``.cmd`` / ``.bat`` targets are wrapped as ``["cmd", "/c", ...]`` because
    CreateProcess refuses to start them directly. Other executables are
    returned unchanged.
    """
    if not full:
        return full
    exe = str(full[0]).lower()
    if exe.endswith((".cmd", ".bat")):
        return ["cmd", "/c"] + full
    return full
