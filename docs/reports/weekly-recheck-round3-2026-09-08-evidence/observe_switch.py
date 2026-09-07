"""Read-only behavioral observation of the current switch probe."""
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts.perf import w3_switch_roundtrip as probe
from AssetsManager.widgets.workspace_bar import WorkspaceSection

active = threading.Event()
started = threading.Event()
observations = []
original_fire = probe._fire_inflight
original_add = WorkspaceSection.add_library

def observe_fire(*args, **kwargs):
    active.set()
    started.set()
    try:
        return original_fire(*args, **kwargs)
    finally:
        active.clear()

def observe_add(self, *args, **kwargs):
    if started.is_set():
        observations.append({"request_active_at_switch": active.is_set()})
    return original_add(self, *args, **kwargs)

probe._fire_inflight = observe_fire
WorkspaceSection.add_library = observe_add
try:
    code = probe.main()
finally:
    Path("artifacts/switch-overlap.json").write_text(
        json.dumps(observations, indent=2), encoding="utf-8")
    print("OVERLAP:", json.dumps(observations))
sys.exit(code)
