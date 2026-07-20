# FileList Command Inventory

This inventory is the baseline for incremental command consistency work. It
describes the current implementation, not a new command framework.

| Command | Shortcut | Shared menu | Operation entry point |
| --- | --- | --- | --- |
| Open | Enter | yes | `_navigate_or_open` |
| Copy | Ctrl+C | yes | `_copy_selected` / `_copy_paths` |
| Cut | Ctrl+X | yes | `_cut_selected` / `_copy_paths` |
| Paste | Ctrl+V | empty area | `_paste` |
| Rename | F2 | single selection | `_inline_rename` / `_rename` |
| Duplicate | Ctrl+D | yes | `_duplicate_selected` |
| Trash delete | Delete | yes | `_delete_selected` / `_delete` |
| Permanent delete | Shift+Delete | yes | `_delete_selected_permanent` / `_delete_permanent` |
| Undo | Ctrl+Z | yes | `_undo` |
| Redo | Ctrl+Y | yes | `_redo` |
| Select all | Ctrl+A | empty area | `_select_all` |
| New folder | Ctrl+Shift+N | empty area | `_new_folder` |
| Refresh | F5 | empty area, toolbar | `_do_refresh` |
| Toggle hidden | Ctrl+H | empty area, toolbar | `_toggle_hidden` |

## Current Contract

- Grid and Details build their selection menus through
  `QWidgetFileListPanel._build_context_menu`.
- The legacy list-view callback delegates to the same builder; it must not
  maintain a separate action list.
- File Open in a FileList menu and Enter both navigate directories and emit
  `file_double_clicked` for files. External opening remains the explicit
  `Reveal in Explorer` action.
- File mutations continue through the scoped FileOperationService and Undo
  service. Menu unification does not create a second mutation path.
- Empty-area Paste remains visible but disabled until FileList or the system
  clipboard contains local files; the mutation guard still rejects unscoped
  work.

## Verified Baseline

`tests/desktop/test_file_list_shim.py` covers:

- common file and directory menu action presence;
- empty-area command presence and Paste availability;
- menu Open's internal FileList behavior;
- shortcut dispatch for every listed command, including Grid/Details Enter,
  Alt+Enter, Escape, search, navigation, and destructive-operation paths.

Future work can add command descriptors incrementally without changing the
covered operation paths or the scoped-service boundary.
