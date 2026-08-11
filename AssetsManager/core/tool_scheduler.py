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
    """Load tools from JSON, falling back to defaults (read-only).

    A missing file yields the defaults without writing anything:
    ``list_tools`` is a query and must not touch the filesystem (the
    shared dir may be read-only, e.g. installed under Program Files).
    Persistence happens only through the explicit ``set_tools`` save path.
    """
    if not TOOLS_PATH.exists():
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


def set_tools(tools: list[dict]) -> None:
    """Persist the full tool list, creating tools.json on first save."""
    if not isinstance(tools, list) or not all(
            isinstance(t, dict) for t in tools):
        raise ValueError("tools must be a list of tool dicts")
    _save(tools)


def run_tool(tool: dict, file_path: str = "", folder_path: str = "",
             timeout: float | None = None) -> None:
    """Execute a tool with substituted arguments.

    Fire-and-forget by default: returns right after launching, which is the
    contract of the GUI menu callers (they start long-running apps like
    Blender/VS Code).  Pass ``timeout`` (seconds) to wait for the tool to
    exit; a hung process is terminated (``kill`` as a fallback) and the
    event is logged as a warning.
    """
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
            proc = subprocess.Popen(_windows_launch_command(full), shell=False)
        else:
            proc = subprocess.Popen(full, shell=False, start_new_session=True)
    except OSError:
        _log.exception("Failed to launch tool: %s", cmd)
        return None
    _log.debug("Launched tool %s (pid=%s)", name, getattr(proc, "pid", None))
    if timeout is not None:
        _wait_for_tool(proc, name, timeout)


# Seconds allowed for a terminated tool to exit before the kill fallback.
_TERMINATE_GRACE = 5.0


def _wait_for_tool(proc: subprocess.Popen, name: str, timeout: float) -> None:
    """Wait for a tool; terminate it (kill as a fallback) if it hangs."""
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pid = getattr(proc, "pid", None)
        _log.warning("Tool %s (pid=%s) timed out after %.1fs; terminating",
                     name, pid, timeout)
        try:
            proc.terminate()
        except OSError:
            _log.exception("Failed to terminate tool %s (pid=%s)", name, pid)
            return
        try:
            proc.wait(timeout=_TERMINATE_GRACE)
        except subprocess.TimeoutExpired:
            _log.warning("Tool %s (pid=%s) ignored terminate; killing",
                         name, pid)
            try:
                proc.kill()
            except OSError:
                _log.exception("Failed to kill tool %s (pid=%s)", name, pid)


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
