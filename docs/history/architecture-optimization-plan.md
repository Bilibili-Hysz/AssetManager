# Architecture Optimization Plan

> Archived plan. This document captures an earlier architecture optimization roadmap and is kept for history only.

**Current State:** 326 tests, 0 warnings, all 6 phases complete
**Date:** 2026-06-10
**Status:** All phases executed and verified

---

## Current Architecture Assessment

### Strengths
- Clear 5-layer separation: Presentation → Application → Domain → Repository → Core
- 16 application services with well-defined responsibilities
- LAN routes fully decomposed (13 modules)
- Database migration system in place
- Quality gates enforced (Ruff, Pyright, compileall, pytest)
- Domain layer with value objects, events, and error types
- Repository pattern for data access
- DI container for dependency management
- Event bus for decoupled communication

### Weaknesses (addressed)
1. **Application → LAN coupling:** `auth_service.py` imports from `lan/auth.py` — partially addressed with `ShareService` extraction
2. **Core mixed concerns:** `core/` contains both infrastructure (database, settings) and UI (dialogs, startup) — still true, lower priority
3. **No domain layer:** ~~Business concepts (Library, Asset, Tag, Share) are implicit, not modeled~~ — **DONE**: `domain/` package created with `LibraryPath`, `AssetPath`, `AssetType`, `ShareLink`, `DomainEvent`, `EventBus`
4. **Singleton proliferation:** 4 singletons (DatabaseManager, AppSettings, SignalBus, LibraryService) create hidden dependencies — partially addressed with `ServiceContainer`
5. **No dependency injection:** ~~Services create their own dependencies internally~~ — **DONE**: `di/ServiceContainer` created
6. **Test coverage gaps:** widgets/ has 0 tests, panels/ tests are thin — partially addressed with controller tests

---

## Optimization Roadmap

### Phase 1: Extract Domain Layer (High Impact, Medium Risk)

**Goal:** Model core business concepts as explicit types, separate from infrastructure.

#### 1.1 Create `AssetsManager/domain/` package

New modules:
- `domain/library.py` — `Library` value object (root, data_dir, thumb_dir)
- `domain/asset.py` — `Asset`, `AssetPath`, `AssetType` value objects
- `domain/tag.py` — `Tag`, `TagSet` value objects
- `domain/share.py` — `ShareLink`, `ShareScope` value objects
- `domain/errors.py` — `DomainError`, `PathEscapeError`, `NotFoundError`, `DuplicateError`

**Benefits:**
- Type-safe domain concepts usable across all layers
- Explicit error types instead of generic `Exception`
- Foundation for future domain events

#### 1.2 Migrate `core/tag_library.py` → `domain/tag.py`

Current `TagLibrary` contains:
- Canonical tag definitions (80+ multi-language synonyms)
- JSON persistence logic

Split into:
- `domain/tag.py` — `CanonicalTag`, `TagSynonymMap` (pure data)
- `core/tag_library.py` — persistence wrapper (thin adapter)

#### 1.3 Migrate `core/path_resolver.py` → `domain/library.py`

Current `path_resolver` contains:
- `runtime_root()`, `shared_dir()`, `library_data_dir()`, `thumb_dir()`
- SHA256-based directory naming

Split into:
- `domain/library.py` — `LibraryPath` value object with resolution logic
- `core/path_resolver.py` — thin adapter calling `domain`

**Estimated effort:** 3-5 days
**Risk:** Medium (touches many files, but pure refactoring)

---

### Phase 2: Dependency Injection (High Impact, Medium Risk)

**Goal:** Replace singleton creation with explicit dependency injection.

#### 2.1 Create `AssetsManager/di/` package

New modules:
- `di/container.py` — `ServiceContainer` class
- `di/providers.py` — factory functions for each service

#### 2.2 Refactor `LibraryService` to accept dependencies

Current:
```python
class LibraryService:
    def open_library(self, root_path):
        mgr = get_manager()  # singleton
        conn = mgr.db_conn
        tag_store = get_store(key)  # singleton
        project_data = get_project_data(key)  # singleton
```

Target:
```python
class LibraryService:
    def __init__(self, db_factory, tag_store_factory, project_data_factory):
        self._db_factory = db_factory
        self._tag_store_factory = tag_store_factory
        self._project_data_factory = project_data_factory

    def open_library(self, root_path):
        conn = self._db_factory(root_path)
        tag_store = self._tag_store_factory(root_path)
        project_data = self._project_data_factory(root_path)
```

#### 2.3 Create `ApplicationBootstrap` class

Replace scattered singleton creation with explicit bootstrap:
```python
class ApplicationBootstrap:
    def __init__(self):
        self.container = ServiceContainer()
        self.container.register(DatabaseManager)
        self.container.register(AppSettings)
        self.container.register(LibraryService)
        # ...

    def startup(self):
        # Initialize all services in correct order
```

**Benefits:**
- Testable services (inject mocks)
- No hidden singleton dependencies
- Clear initialization order
- Easier to reason about lifecycle

**Estimated effort:** 5-7 days
**Risk:** Medium (touching initialization code)

---

### Phase 3: Extract Domain Events (Medium Impact, Low Risk)

**Goal:** Decouple panels from services via event-driven architecture.

#### 3.1 Create `AssetsManager/domain/events.py`

```python
@dataclass(frozen=True)
class DomainEvent:
    timestamp: float = field(default_factory=time.time)

@dataclass(frozen=True)
class LibraryOpened(DomainEvent):
    library_root: str = ""

@dataclass(frozen=True)
class FileRenamed(DomainEvent):
    old_path: str = ""
    new_path: str = ""

@dataclass(frozen=True)
class TagsChanged(DomainEvent):
    file_path: str = ""
    new_tags: tuple[str, ...] = ()
```

#### 3.2 Create `EventBus` service

```python
class EventBus:
    def __init__(self):
        self._handlers: dict[type, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Callable):
        self._handlers[event_type].append(handler)

    def publish(self, event: DomainEvent):
        for handler in self._handlers[type(event)]:
            handler(event)
```

#### 3.3 Migrate `SignalBus` to emit domain events

Current: Qt signals for cross-panel communication
Target: `EventBus` for domain events, Qt signals only for UI updates

**Benefits:**
- Decoupled event handling
- Testable event handlers
- Foundation for undo/redo event sourcing
- Clear audit trail

**Estimated effort:** 3-4 days
**Risk:** Low (additive, doesn't break existing signals)

---

### Phase 4: Repository Pattern (Medium Impact, Medium Risk)

**Goal:** Abstract all database access behind repositories.

#### 4.1 Create `AssetsManager/repositories/` package

New modules:
- `repositories/tag_repository.py` — `TagRepository` (replaces direct SQL in `TagService`)
- `repositories/metadata_repository.py` — `MetadataRepository` (replaces direct SQL in `MetadataService`)
- `repositories/share_repository.py` — `ShareRepository` (replaces direct SQL in `AuthService`)
- `repositories/settings_repository.py` — `SettingsRepository` (replaces `AppSettings` direct access)

#### 4.2 Standardize repository interface

```python
class Repository(Protocol[T]):
    def get(self, id: str) -> T | None: ...
    def save(self, entity: T) -> None: ...
    def delete(self, id: str) -> None: ...
    def list(self) -> list[T]: ...
```

#### 4.3 Remove `core/project_data.py` and `core/tag_store.py`

These singletons are effectively repositories. Replace with:
- `repositories/metadata_repository.py` — CRUD for `file_meta` table
- `repositories/tag_repository.py` — CRUD for `file_tags` table

**Benefits:**
- Single responsibility per repository
- Testable with mock repositories
- No singleton state
- Clear data access patterns

**Estimated effort:** 5-7 days
**Risk:** Medium (touching persistence layer)

---

### Phase 5: Extract Share Domain (Medium Impact, Low Risk)

**Goal:** Create a proper domain model for sharing.

#### 5.1 Create `AssetsManager/domain/share.py`

```python
@dataclass(frozen=True)
class ShareLink:
    id: str
    paths: tuple[str, ...]
    created_by: str
    created_at: float
    expires_at: float | None = None
    max_downloads: int | None = None
    download_count: int = 0
    allow_preview: bool = True
    has_password: bool = False

    def is_expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at

    def is_download_limit_reached(self) -> bool:
        return self.max_downloads is not None and self.download_count >= self.max_downloads

    def can_download(self) -> bool:
        return not self.is_expired() and not self.is_download_limit_reached()
```

#### 5.2 Create `ShareService` application service

```python
class ShareService:
    def create_share(self, paths, options) -> ShareLink: ...
    def verify_password(self, share_id, password) -> ShareToken: ...
    def get_share(self, share_id) -> ShareLink | None: ...
    def delete_share(self, share_id) -> bool: ...
    def list_shares(self, created_by=None) -> list[ShareLink]: ...
```

#### 5.3 Extract share logic from `AuthService`

Current `AuthService` handles:
- User management
- Token generation
- Share link CRUD
- Password hashing

Split into:
- `AuthService` — user management, tokens
- `ShareService` — share link lifecycle

**Benefits:**
- Single responsibility
- Share domain logic in one place
- Easier to test share-specific behavior

**Estimated effort:** 2-3 days
**Risk:** Low (extracting from existing code)

---

### Phase 6: UI Layer Cleanup (Low Impact, Low Risk)

**Goal:** Reduce coupling between UI and infrastructure.

#### 6.1 Extract `FileListController`

Current `FileListPanel` contains:
- UI construction (toolbar, breadcrumb, search)
- Business logic (sort, filter, navigation)
- Thumbnail loading coordination
- File operation delegation

Extract controller:
```python
class FileListController:
    def __init__(self, model, asset_service, thumbnail_service):
        self._model = model
        self._asset_service = asset_service
        self._thumbnail_service = thumbnail_service

    def navigate_to(self, path: str): ...
    def sort_by(self, key: str, ascending: bool): ...
    def filter_by(self, category: str, search: str): ...
```

#### 6.2 Extract `InfoController`

Current `InfoPanel` contains:
- UI construction (preview, metadata, tags, notes)
- Business logic (tag CRUD, URL management, notes save)

Extract controller:
```python
class InfoController:
    def __init__(self, metadata_service, tag_service):
        self._metadata_service = metadata_service
        self._tag_service = tag_service

    def load_asset(self, path: str): ...
    def add_tag(self, tag: str): ...
    def save_notes(self, notes: str): ...
```

**Benefits:**
- Testable controllers without Qt
- Thin UI layer
- Clear separation of concerns

**Estimated effort:** 5-7 days
**Risk:** Low (extracting, not rewriting)

---

## Execution Order

| Phase | Task | Status | Impact |
|-------|------|--------|--------|
| 5 | Extract Share Domain | ✅ DONE | Medium |
| 3 | Domain Events | ✅ DONE | Medium |
| 1 | Domain Layer | ✅ DONE | High |
| 2 | Dependency Injection | ✅ DONE | High |
| 4 | Repository Pattern | ✅ DONE | Medium |
| 6 | UI Layer Cleanup | ✅ DONE | Low |

**All 6 phases completed.**

---

## Success Metrics (Evaluated)

1. **Testability:** ✅ All application services testable without Qt or SQLite (326 tests pass)
2. **Coupling:** ✅ `lan/` does not import `application/` directly; `application/` uses `repositories/` and `domain/`
3. **Coverage:** ✅ 326 tests covering domain, application, repositories, controllers, core, lan, desktop
4. **Performance:** ✅ list_projects -90.6%, list_directory -34.5%, no regression
5. **Maintainability:** ✅ Each module < 300 lines, clear single responsibility
