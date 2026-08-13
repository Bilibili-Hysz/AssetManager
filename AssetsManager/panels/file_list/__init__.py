"""File list panel — QWidget grid canvas (single concrete panel).

The panel is a QPainter-drawn grid with a QTreeView Details mode; the
QListView era and its compatibility shims are gone. The one class is
FileListPanel, defined in _base.py (toolbar/header/navigation in the
mixins _navigation/_actions/_commands).
"""
from AssetsManager.panels.file_list._base import FileListPanel

__all__ = ["FileListPanel"]
