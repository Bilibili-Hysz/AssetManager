# FileList Interaction Paradigm Design

> **Status**: Proposed product interaction model; no production behavior changes are implied by this document.
> **Inputs**: `filelist-product-and-context-menu-suggestions-2026-07-19.md`, `filelist-command-inventory-2026-07-19.md`, and the current FileList implementation.
> **Scope**: Desktop `AssetsManager/panels/file_list/` only.

## 1. Product Thesis

FileList should behave as an **asset workspace**, not as a collection of
independent menus and callbacks:

> **Context chooses a command; the command chooses a safe operation; a visible
> operation record explains the result.**

This creates one learnable workflow across Grid, Details, keyboard, toolbar,
and drag/drop without moving filesystem work into presentation code.

The model has four user-facing surfaces:

1. **Browse surface** — Grid or Details presents the same selection, sort,
   search, filter, navigation, and status model.
2. **Command surface** — context menu, keyboard, toolbar, and later command
   palette project the same command availability and labels.
3. **Operation surface** — a compact non-modal activity strip reports started,
   progress-capable, completed, partial-failure, and undoable operations.
4. **State surface** — empty, filtered-empty, scanning, unavailable, and
   permission-failure states explain what happened and offer the next safe
   action.

## 2. Current Baseline And Reusable Seams

The first implementation must reuse existing seams instead of replacing the
FileList architecture:

| Concern | Existing seam | Keep / change |
| --- | --- | --- |
| Shared selected-item menu | `QWidgetFileListPanel._build_context_menu()` | Keep as the initial menu projection seam. |
| Keyboard dispatch | `panels/file_list/_shortcuts.py::handle_key()` | Keep as the initial shortcut projection seam. |
| Selection | `_selected_paths()`, Grid selection shim, Details selection model | Keep; normalize into a command context only. |
| Safe mutation | `_capture_mutation_context()` plus scoped `FileOperationService`/`UndoService` | Binding contract; never bypass. |
| Worker execution | `_run_in_background()` and `_background_ops` | Keep; activity reporting wraps, not replaces, this path. |
| Result refresh | session-scoped `FileSystemChanged` debounce plus `_post_refresh()` | Keep session filtering and refresh ownership. |
| Grid/Details menus | Grid/Details both call `_show_context_menu()` | Preserve one builder; legacy callback must remain delegated. |
| External opening | `_navigate_or_open()` versus `_open_in_explorer()` | Preserve semantic distinction and label it consistently. |

## 3. Command Model

Introduce a deliberately small command description, not a generic framework.
A command is a projection record used by FileList only:

```python
@dataclass(frozen=True)
class FileListCommand:
    id: str
    label_key: str
    shortcut: str | None
    group: str
    visible_when: Callable[[FileListCommandContext], bool]
    enabled_when: Callable[[FileListCommandContext], bool]
    invoke: Callable[[FileListCommandContext], None]
```

The context is immutable for one invocation and contains only presentation
facts plus a captured mutation capability when needed:

```python
@dataclass(frozen=True)
class FileListCommandContext:
    paths: tuple[str, ...]
    current_dir: Path
    view_mode: Literal["Grid", "Details"]
    clipboard_has_local_files: bool
    scoped: LibraryScopedServices | None
    undo_available: bool
    redo_available: bool
```

### Non-negotiable command rules

- Context construction does **not** start filesystem work.
- A mutation command invokes the existing action method, which captures the
  originating session/service/root before it enters a worker.
- Menu enabled state is advisory; action-level scoped mutation guards remain
  authoritative for shortcuts, menus, drag/drop, and delayed callbacks.
- Command IDs, labels, shortcuts, and availability are stable. Qt objects and
  callback functions remain implementation details.
- Do not move plugin command execution into this first registry; retain the
  existing plugin submenu adapter until plugin error/lifecycle handling has a
  separately approved scope.

### Stable initial command groups

| Group | Commands | Notes |
| --- | --- | --- |
| Open | `open`, `open_with`, `reveal` | `open` means internal directory navigation or FileList file-open signal; reveal remains explicitly external. |
| Clipboard | `copy`, `cut`, `copy_path`, `paste` | Paste stays visible in empty context and disables when no local source exists. |
| Mutate | `rename`, `duplicate`, `trash`, `permanent_delete`, `new_folder` | Multi-selection keeps Rename visible but disabled unless batch rename is explicitly selected in a later phase. |
| History | `undo`, `redo` | Enabled only from the bound scoped UndoService. |
| Organize | `tags`, `share`, `properties`, `plugins` | Keep existing dialogs/submenus; no forced shortcut allocation. |
| Browse | `select_all`, `refresh`, `toggle_hidden`, `sort`, `view` | Empty-area/contextual commands. |

## 4. Interaction Rules

### 4.1 Context menus and shortcuts

- Grid and Details expose identical selected-item command groups and state.
- Empty-area menus expose paste, new folder, select all, refresh, hidden,
  undo, redo, sort, and view; unavailable commands remain visible and disabled
  where discovery is useful.
- Show shortcuts only for the existing stable bindings: Enter, Ctrl+C,
  Ctrl+X, Ctrl+V, F2, Ctrl+D, Delete, Shift+Delete, Ctrl+Z, Ctrl+Y, Ctrl+A,
  Ctrl+Shift+N, F5, Ctrl+H, Ctrl+F, Backspace, and Alt+Enter.
- Menu Open, double click, and Enter retain the same internal semantics.
  `Reveal in Explorer` is the explicit system-file-manager command, not a
  fallback meaning of Open.
- The first phase does not add a global command palette or user-customizable
  shortcuts. Command metadata makes those later projections possible.

### 4.2 Selection and focus after mutation

- After successful copy/duplicate/create, select the first created result when
  it remains in the current visible directory; otherwise retain current
  selection.
- After rename/move, retain selection by canonical destination path after the
  refresh, never by stale row number.
- After trash/permanent delete, select the nearest surviving adjacent row;
  when none remains, focus the browse surface and show the appropriate state.
- A foreign-session completion may never change selection or focus. Existing
  session/generation checks remain authoritative.

### 4.3 Drag and drop

The visual contract should make existing action semantics observable:

| Source / modifier | Proposed action | UI feedback |
| --- | --- | --- |
| External local files | Copy | Target highlight plus `Copy to <folder>` label. |
| Same-library assets | Move | Target highlight plus `Move to <folder>` label. |
| Same-library assets + Ctrl | Copy | Target highlight plus `Copy to <folder>` label. |
| Drop on a directory item | Target that directory | Highlight directory, not merely current folder. |
| Drop on a file | No implicit directory entry | Reject unless later product scope defines another rule. |

The first drag/drop implementation phase must be visual-only plus target
resolution tests. It must not alter move/copy service semantics until Ctrl
modifier behavior and target handling are independently approved.

### 4.4 Operation activity strip

Long-running FileList mutations should report a single compact activity record
at the bottom of the FileList, above or integrated with existing status text:

```text
Copying 48 of 126 assets to Props/             [Details] [Cancel]
Copied 126 assets                              [Undo]
Completed with 3 failures                      [Details]
```

Minimum record fields:

```text
operation_id, session_token, kind, total, completed, failures,
state(started|running|completed|partial|failed|cancelled), undo_available
```

Rules:

- The strip is an observer of worker outcomes, not a new filesystem worker.
- It is session-bound; session switch/shutdown hides or retires old records
  without redirecting work to the next library.
- Cancel is shown only when the underlying operation has a real cancellation
  capability. Do not present a nonfunctional cancel button for the existing
  synchronous `FileOperationService` calls.
- Completion action uses existing scoped UndoService only when that exact
  operation is undoable; it must not manufacture undo history.
- Partial failure keeps successful projection updates and shows error detail;
  it does not roll back unrelated completed paths.

### 4.5 Browse states

Use explicit state precedence:

1. permission/unavailable error;
2. active scan;
3. filtered/search empty;
4. genuinely empty directory;
5. normal contents.

Each state offers only existing safe actions in the first release:

| State | Message | Actions |
| --- | --- | --- |
| Empty directory | `This folder is empty` | New Folder, Import / Paste when available |
| Search/filter empty | `No matching assets` | Clear search, clear type filter |
| Scanning | `Reading folder…` plus discovered count when available | None; browsing state remains responsive |
| Permission/read failure | `Cannot read this folder` | Retry, Reveal in Explorer |

## 5. Phased Delivery

### Phase A — Command consistency foundation (first implementation slice)

1. Add a FileList-local command context and descriptors for only existing
   commands.
2. Make `_build_context_menu()` project descriptors without changing labels,
   command paths, plugin submenu ownership, or mutation calls.
3. Make `_shortcuts.handle_key()` dispatch the same descriptor IDs.
4. Add command availability tests across Grid, Details, and empty contexts.

**Acceptance:** all existing `test_file_list_shim.py` command/shortcut tests
pass unchanged or are strengthened; no new `FileOperationService()` or
`UndoService()` construction appears in presentation.

### Phase B — Selection continuity and command feedback

1. Record canonical affected paths from existing operation results.
2. Restore focus/selection only after current-session refresh settles.
3. Add operation result messages for copy, move, delete, duplicate, undo, and
   redo; initially completion/partial failure only, without fake progress or
   cancel.

**Acceptance:** tests prove same-session selection restoration and foreign or
closed-session completion discard.

### Phase C — Target-aware drag/drop and truthful progress

1. Add directory-target resolution and visual copy/move affordances.
2. Add Ctrl-copy only after application-service behavior and Undo records are
   specified and tested.
3. Add true aggregate progress only after services expose progress/cancel
   contracts; otherwise retain indeterminate activity feedback.

### Phase D — Asset-specialist workflows

1. Batch rename preview, validation, conflicts, and current-sort numbering.
2. Multi-selection tag panel showing common/partial tags.
3. Saved/combinable filters, full-library search separation, shortcut help,
   and optional customization.

## 6. Guardrails And Test Matrix

The design must preserve these existing contracts:

- File mutations are session-bound, use `FileOperationService`/`UndoService`,
  and fail closed when scoped services are absent.
- `FileSystemChanged` refresh remains session-token filtered and debounced.
- Grid/Details menu construction remains one path; the legacy list callback
  delegates rather than maintaining a divergent action list.
- Background operations capture session, services, root, and resolved paths
  before dispatch; library switch cannot redirect them.
- Async FileList teardown/generation protections, thumbnail scheduling, and
  Qt callback lifetime protections remain out of scope.
- New UI controls use `scaled_px()`/`scaled_pt()` and theme tokens.

Required test layers for each phase:

| Concern | Focused coverage |
| --- | --- |
| Command projection | `tests/desktop/test_file_list_shim.py` menu labels, enablement, Grid/Details parity, shortcut dispatch |
| Operation safety | `tests/integration/test_file_operation_service.py`, `tests/integration/test_undo_service.py` |
| Scoped lifecycle | `tests/desktop/test_file_list_shim.py`, `tests/desktop/test_scoped_service_access.py`, architecture boundaries |
| Selection/async identity | FileList desktop tests plus current session-routing regressions |
| Drag/drop | existing FileList shim external/in-library/no-scoped-service tests, expanded for target/modifier matrix |
| Full handoff | Ruff, Pyright, compileall, root pytest |

## 7. Explicit Non-Goals

- No generic cross-application command framework in Phase A.
- No direct filesystem, database, worker, or Undo implementation in a Qt menu
  or toolbar callback.
- No product promise of cancellation until the service layer can honor it.
- No bulk rename execution change before preview/conflict design is approved.
- No rewrite of Grid renderer, thumbnail runtime, session lifecycle, plugin
  host, or LAN API as part of command consistency work.

## 8. First Approved Implementation Candidate

The safest next coding task is **Phase A.1**:

> Add a minimal FileList-local command descriptor/context used only by the
> shared selected-item and empty-area context-menu builders, while preserving
> the existing action methods and source-test seam. Add no toolbar projection
> and do not reroute keyboard dispatch in the first commit.

This establishes declarative availability and stable IDs with the smallest
behavioral surface. A second independently tested slice can then route stable
shortcuts through the same IDs.
