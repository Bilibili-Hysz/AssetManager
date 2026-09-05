"""D7: single sources of truth for the scoped-panel mount lists.

Panels named here receive per-library scoped services via
``MainWindow._apply_scoped_services`` and participate in
``WindowLifecycleCoordinator`` orchestration. ``MainWindow`` and
``window_lifecycle_coordinator`` both import these tuples so the injection
loop and the lifecycle loops iterate the same lists — adding a panel means
changing one name here.

This module stays Qt-free so test window stubs can import the tuples
without pulling in PySide6, and so the lifecycle coordinator keeps its
duck-typed ``Any`` window contract.

The two tuples deliberately differ:
- SWITCH_PANELS covers the full switch_library choreography — every scoped
  panel gets prepare_library_switch, and the session swap happens before
  any navigation, so file_list participates like the rest.
- SHUTDOWN_BEFORE_SAVE_PANELS is only the *early* phase of
  shutdown_resources; file_list is shut down separately AFTER dock/workspace
  state is persisted (it is the largest panel and holds the most background
  work — its teardown must not race the layout save).
"""
from __future__ import annotations

# "tag_tree" is intentionally absent as a mounted dock — tag filtering lives
# in TagBrowserDialog, which owns its own instance (and its own runtime
# subscription). Both consumer loops tolerate a missing attribute so a
# future in-window TagTreePanel slots in unchanged.
SWITCH_PANELS: tuple[str, ...] = ("info", "file_list", "sidebar", "tag_tree")

SHUTDOWN_BEFORE_SAVE_PANELS: tuple[str, ...] = ("info", "sidebar", "tag_tree")
