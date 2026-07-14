"""Controllers — business logic extracted from UI panels.

Controllers provide testable business logic that panels delegate to.
They have no Qt dependencies and can be tested with pure Python.

Modules:
    file_list_controller.py  — File browsing business logic
    info_controller.py       — InfoPanel data access (metadata, tags, URLs, plugins)
    tag_tree_controller.py   — TagTreePanel data access (tag CRUD, file lookup)
"""
