"""Restore flow orchestration, failure state and admission control.

``RestoreMixin`` owns the mutation half of backup restore: admission gating
and acknowledgement, the reserved restore transaction (validate, extract to
staging, quarantine, install, rollback), the process-local/canonical failure
state, and restore quarantine inspection.

Archive reading and extraction policy live in ``_validate.py``; backup
creation lives in ``_export.py``; ``library_export_service.py`` composes the
three.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import uuid
import zipfile
from typing import TYPE_CHECKING, BinaryIO

from AssetsManager.application.library_export_io import (
    assert_real_staging_tree,
    quick_check_database_file,
    restore_quarantine_path,
    safe_restore_quarantine_root,
)
from AssetsManager.application.library_export_service_types import (
    LibraryRestoreResult,
    RestoreAdmissionBlockedError,
    RestoreFailureState,
    RestoreQuarantineEntry,
)
from AssetsManager.core.path_resolver import root_identity

if TYPE_CHECKING:
    import threading
    from typing import Callable, ContextManager

    from AssetsManager.application.context import LibrarySession
    from AssetsManager.application.library_export_service_types import (
        BackupValidationResult,
    )
    from AssetsManager.core.path_resolver import RootIdentity


class RestoreMixin:
    """Restore flow, failure-state management and admission control."""

    if TYPE_CHECKING:
        # Host surface owned by LibraryExportService / sibling mixins.
        _session: LibrarySession | None
        _restore_coordinator: Callable[
            [LibrarySession, str | Path | RootIdentity], ContextManager[None]
        ] | None
        _restore_state_provider: Callable[[str | Path], object | None] | None
        _restore_acknowledger: Callable[[str | Path, str], object | None] | None
        _restore_state_lock: threading.Lock
        _restore_failure_state: RestoreFailureState | None

        _BACKUP_DATA_ROOT: str
        _MAX_DATABASE_QUICK_CHECK_SIZE: int
        _QUICK_CHECK_CACHE_KIB: int

        @classmethod
        def _preflight_archive_path(cls, archive_path: Path | BinaryIO) -> None: ...

        @classmethod
        def _assert_real_contained(
            cls, root: Path, candidate: Path, *, kind: str
        ) -> Path: ...

        @staticmethod
        def _is_link_or_junction(path: Path) -> bool: ...

        def _validate_open_backup(
            self,
            archive: zipfile.ZipFile,
            *,
            expected_library_root: str | Path | None = None,
            should_cancel: Callable[[], bool] | None = None,
        ) -> tuple[BackupValidationResult, tuple[tuple[str, dict], ...]]: ...

        def _extract_validated_backup(
            self,
            archive: zipfile.ZipFile,
            destination: Path,
            entries: tuple[tuple[str, dict], ...],
        ) -> None: ...


    @staticmethod
    def _external_state_value(state: object, name: str, default: object = None) -> object:
        if isinstance(state, dict):
            return state.get(name, default)
        return getattr(state, name, default)

    def _external_restore_state(self) -> RestoreFailureState | None:
        if self._restore_state_provider is None or self._session is None:
            return None
        external = self._restore_state_provider(self._session.root)
        if external is None or external == {}:
            return None
        secondary = self._external_state_value(external, "secondary_errors", ())
        if not isinstance(secondary, tuple):
            secondary = tuple(secondary) if isinstance(secondary, (list, set)) else ()
        generation_value = self._external_state_value(external, "generation")
        token_value = self._external_state_value(external, "token")
        generation = generation_value if isinstance(generation_value, int) else None
        token = token_value if isinstance(token_value, str) else None
        return RestoreFailureState(
            phase=str(self._external_state_value(external, "phase", "restore")),
            message=str(self._external_state_value(external, "message", "Restore recovery required")),
            secondary_errors=secondary,
            generation=generation,
            token=token,
        )

    @property
    def restore_failure_state(self) -> RestoreFailureState | None:
        """Return canonical recovery evidence, falling back to the local mirror."""
        external = self._external_restore_state()
        if external is not None:
            return external
        with self._restore_state_lock:
            return self._restore_failure_state

    def acknowledge_restore_failure(
        self, token: str | None = None
    ) -> RestoreFailureState | None:
        """Compare-and-delete canonical state, then clear the local mirror.

        A local mirror is intentionally preferred when no explicit token is
        supplied: a stale ExportService must not silently adopt and clear a
        newer process-level poison. Bootstrap-bound callers pass the recovery
        token captured from the canonical provider when they own the ACK.
        """
        with self._restore_state_lock:
            local = self._restore_failure_state
        external = self._external_restore_state()
        previous = local or external
        if self._restore_acknowledger is not None and self._session is not None:
            # A default ACK is local-only.  It must not submit a stale local
            # token to a process-global adapter, even when that adapter accepts
            # arbitrary tokens.  Only an explicit token is authority to clear
            # global state.
            if token is None:
                if external is not None:
                    return external
                with self._restore_state_lock:
                    self._restore_failure_state = None
                return previous
            acked_state = external or previous
            self._restore_acknowledger(self._session.root, token)
            remaining = self._external_restore_state()
            if remaining is not None:
                return remaining
            with self._restore_state_lock:
                self._restore_failure_state = None
            return acked_state
        with self._restore_state_lock:
            self._restore_failure_state = None
        return previous

    def _ensure_restore_admission(self) -> None:
        state = self.restore_failure_state
        if state is not None:
            raise RestoreAdmissionBlockedError(state)

    def restore_backup(
        self,
        archive_path: str | Path,
        library_root: str | Path,
        *,
        overwrite_existing: bool = False,
    ) -> LibraryRestoreResult:
        """Restore one archive while holding the service's root reservation."""
        from AssetsManager.application.library_export_service import (
            LibraryLock,
            library_data_dir,
            library_lock_path,
        )

        self._ensure_restore_admission()
        if self._session is None or self._restore_coordinator is None:
            raise RuntimeError("Restore requires an injected ownership coordinator")
        identity = root_identity(library_root)
        session_context = getattr(self._session, "context", None)
        session_key = getattr(session_context, "root_key", None)
        if session_key is not None and identity.map_key != session_key:
            raise RuntimeError("Restore target does not match the bound library session")
        root = identity.display_path
        if not root.is_dir():
            raise FileNotFoundError(root)

        data_dir = library_data_dir(identity)
        target = Path(archive_path).resolve()
        staging = data_dir.parent / f".{data_dir.name}.restore-{uuid.uuid4().hex}"
        # Admission-only checks happen before the coordinator reservation. This
        # keeps missing/invalid archives and unconfirmed overwrites from being
        # interpreted as process-poisoning restore failures by older owners.
        try:
            self._preflight_archive_path(target)
            if data_dir.exists() or data_dir.is_symlink():
                if self._is_link_or_junction(data_dir):
                    raise ValueError("Refusing to replace a linked or reparse-pointed RuntimeData directory")
                if not overwrite_existing:
                    raise FileExistsError(
                        "Target RuntimeData directory exists; explicit overwrite is required"
                    )
        except BaseException as admission_error:
            self._mark_restore_error_nonpoison(admission_error)
            raise
        with self._restore_coordinator(self._session, identity):
            # A caller may have queued before an earlier restore poisoned state.
            self._ensure_restore_admission()
            try:
                lock = LibraryLock(library_lock_path(identity))
            except BaseException as lock_error:
                self._mark_restore_error_nonpoison(lock_error)
                raise
            try:
                return self._restore_under_reservation(
                    target,
                    root,
                    data_dir,
                    staging,
                    overwrite_existing=overwrite_existing,
                )
            finally:
                active_error = sys.exc_info()[1]
                try:
                    released = lock.release()
                    if not released:
                        raise RuntimeError(f"Failed to release library lock: {lock.path}")
                except BaseException as release_error:
                    self._record_restore_failure(release_error, "library lock release")
                    if active_error is None:
                        raise
                    self._add_restore_secondary_error(
                        active_error, "library lock release", release_error
                    )

    def _restore_under_reservation(
        self,
        target: Path,
        root: Path,
        data_dir: Path,
        staging: Path,
        *,
        overwrite_existing: bool,
    ) -> LibraryRestoreResult:
        previous: Path | None = None
        moved_existing = False
        installed = False
        mutation_phase: str | None = None
        archive_stream: BinaryIO | None = None
        try:
            try:
                archive_stream = target.open("rb")
                self._preflight_archive_path(archive_stream)
                archive_stream.seek(0)
                archive_context = zipfile.ZipFile(archive_stream, mode="r")
            except BaseException as exc:
                self._mark_restore_error_nonpoison(exc)
                raise
            with archive_context as archive:
                validation, entries = self._validate_open_backup(
                    archive, expected_library_root=root
                )
                if not validation.valid:
                    raise ValueError(
                        "Backup validation failed: " + "; ".join(validation.errors)
                    )
                if data_dir.exists() or data_dir.is_symlink():
                    if self._is_link_or_junction(data_dir):
                        raise ValueError("Refusing to replace a linked or reparse-pointed RuntimeData directory")
                    if not overwrite_existing:
                        raise FileExistsError(
                            "Target RuntimeData directory exists; explicit overwrite is required"
                        )

                staging.mkdir(parents=True, exist_ok=False)
                mutation_phase = "staging"
                self._extract_validated_backup(archive, staging, entries)
            if archive_stream is not None:
                try:
                    archive_stream.close()
                except BaseException as close_error:
                    archive_stream = None
                    self._record_restore_failure(close_error, mutation_phase or "staging")
                    raise
                archive_stream = None
            mutation_phase = "staging quick_check"
            self._quick_check_database_file(staging / "assetmanager.db")

            if data_dir.exists():
                mutation_phase = "quarantine"
                previous = self._restore_quarantine_path(data_dir)
                self._assert_real_contained(data_dir.parent, data_dir, kind="RuntimeData directory")
                self._assert_real_contained(data_dir.parent, previous.parent, kind="Restore quarantine directory")
                data_dir.replace(previous)
                moved_existing = True
            mutation_phase = "install"
            self._assert_real_staging_tree(staging, entries)
            self._assert_real_contained(data_dir.parent, data_dir.parent, kind="RuntimeData root directory")
            staging.replace(data_dir)
            installed = True
            mutation_phase = "installed quick_check"
            self._assert_real_contained(data_dir.parent, data_dir, kind="RuntimeData directory")
            self._quick_check_database_file(data_dir / "assetmanager.db")
            return LibraryRestoreResult(
                library_root=root,
                data_dir=data_dir,
                previous_data_dir=previous,
                file_count=validation.file_count,
            )
        except BaseException as primary_error:
            if mutation_phase is None:
                if archive_stream is not None:
                    try:
                        archive_stream.close()
                    except BaseException:
                        pass
                    archive_stream = None
                self._mark_restore_error_nonpoison(primary_error)
                raise
            # Canonical poison is established before any best-effort cleanup or
            # stream close. Cleanup success must not make a mutation failure safe.
            self._record_restore_failure(primary_error, mutation_phase)
            if archive_stream is not None:
                try:
                    archive_stream.close()
                except BaseException as close_error:
                    self._add_restore_secondary_error(
                        primary_error, "archive stream close", close_error
                    )
                finally:
                    archive_stream = None
            try:
                if installed and (data_dir.exists() or data_dir.is_symlink()):
                    self._move_to_restore_quarantine(data_dir, root, "failed-install")
                elif staging.exists() or staging.is_symlink():
                    self._move_to_restore_quarantine(staging, root, "failed-staging")
            except BaseException as quarantine_error:
                self._add_restore_secondary_error(
                    primary_error, "failed restore quarantine", quarantine_error
                )
            if (
                moved_existing
                and previous is not None
                and previous.exists()
                and not data_dir.exists()
                and not data_dir.is_symlink()
            ):
                try:
                    self._restore_previous_data(previous, data_dir)
                except BaseException as rollback_error:
                    self._add_restore_secondary_error(
                        primary_error, "previous RuntimeData rollback", rollback_error
                    )
            raise

    @classmethod
    def _restore_previous_data(cls, previous: Path, data_dir: Path) -> None:
        runtime_root = data_dir.parent
        cls._assert_real_contained(
            runtime_root, previous, kind="Rollback previous RuntimeData directory"
        )
        cls._assert_real_contained(
            runtime_root, runtime_root, kind="Rollback RuntimeData parent directory"
        )
        if cls._is_link_or_junction(previous):
            raise ValueError("Rollback previous path is a link or junction")
        if os.path.lexists(data_dir) and cls._is_link_or_junction(data_dir):
            raise ValueError("Rollback target path is a link or junction")
        cls._assert_real_contained(
            runtime_root, previous, kind="Rollback previous RuntimeData directory"
        )
        cls._assert_real_contained(
            runtime_root, data_dir.parent, kind="Rollback RuntimeData parent directory"
        )
        previous.replace(data_dir)

    @staticmethod
    def _mark_restore_error_retryable(error: BaseException) -> None:
        try:
            setattr(error, "restore_retryable", True)
        except (AttributeError, TypeError):
            pass

    @staticmethod
    def _mark_restore_error_nonpoison(error: BaseException) -> None:
        try:
            setattr(error, "restore_poison", False)
            setattr(error, "restore_recovery_required", False)
        except (AttributeError, TypeError):
            pass

    def _record_restore_failure(self, error: BaseException, phase: str) -> None:
        secondary_errors = tuple(getattr(error, "restore_secondary_errors", ()))
        existing_state = getattr(error, "restore_failure_state", None)
        if isinstance(existing_state, RestoreFailureState):
            token = existing_state.token
            generation = existing_state.generation
            canonical_phase = existing_state.phase
        else:
            token = getattr(error, "restore_token", None) or uuid.uuid4().hex
            external = self._external_restore_state()
            generation = (
                getattr(error, "restore_generation", None)
                if isinstance(getattr(error, "restore_generation", None), int)
                else (external.generation if external is not None else 0)
            )
            canonical_phase = phase
        state = RestoreFailureState(
            phase=canonical_phase,
            message=f"{type(error).__name__}: {error}",
            secondary_errors=secondary_errors,
            generation=generation,
            token=token,
        )
        with self._restore_state_lock:
            self._restore_failure_state = state
        self._mark_restore_error_retryable(error)
        try:
            setattr(error, "restore_admission_blocked", True)
            setattr(error, "restore_recovery_required", True)
            setattr(error, "restore_poison", True)
            setattr(error, "restore_failure_state", state)
            setattr(error, "restore_token", token)
            setattr(error, "restore_generation", generation)
        except (AttributeError, TypeError):
            pass

    def _add_restore_secondary_error(
        self, primary: BaseException, phase: str, secondary: BaseException
    ) -> None:
        detail = f"{phase}: {type(secondary).__name__}: {secondary}"
        existing = tuple(getattr(primary, "restore_secondary_errors", ()))
        try:
            setattr(primary, "restore_secondary_errors", (*existing, detail))
            primary.add_note(f"Restore secondary failure ({detail})")
        except (AttributeError, TypeError):
            pass
        # Preserve the canonical primary token/phase while publishing the new
        # secondary evidence; never rotate global ACK identity during cleanup.
        canonical = getattr(primary, "restore_failure_state", None)
        self._record_restore_failure(
            primary, canonical.phase if isinstance(canonical, RestoreFailureState) else phase
        )

    def list_restore_quarantine(
        self, library_root: str | Path
    ) -> tuple[RestoreQuarantineEntry, ...]:
        """List direct, non-link directories in this library's restore quarantine.

        The result is read-only and deliberately does not recurse into entries.
        The library lock is held for the complete inspection so a concurrent
        restore cannot change the set while it is being enumerated.
        """
        from AssetsManager.application.library_export_service import (
            LibraryLock,
            library_data_dir,
            library_lock_path,
        )

        root = Path(library_root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(root)

        data_dir = library_data_dir(root)
        lock = LibraryLock(library_lock_path(root))
        try:
            try:
                quarantine_root = self._safe_restore_quarantine_root(
                    data_dir, create_missing=False
                )
            except ValueError:
                runtime_root = data_dir.parent
                for component in (
                    runtime_root / "_orphaned",
                    runtime_root / "_orphaned" / "restore-backups",
                ):
                    if (
                        component.exists()
                        and not component.is_dir()
                        and not self._is_link_or_junction(component)
                    ):
                        return ()
                raise
            if quarantine_root is None:
                return ()

            entries: list[RestoreQuarantineEntry] = []
            for candidate in sorted(
                quarantine_root.iterdir(),
                key=lambda path: (path.name.casefold(), path.name),
            ):
                if not candidate.is_dir() or self._is_link_or_junction(candidate):
                    continue
                try:
                    canonical = candidate.resolve()
                    canonical.relative_to(quarantine_root)
                    if canonical.parent != quarantine_root:
                        continue
                    modified_at = datetime.fromtimestamp(
                        candidate.stat().st_mtime, tz=timezone.utc
                    )
                    is_empty = next(candidate.iterdir(), None) is None
                except (OSError, RuntimeError, StopIteration):
                    continue
                entries.append(
                    RestoreQuarantineEntry(
                        path=candidate,
                        name=candidate.name,
                        modified_at=modified_at,
                        is_empty=is_empty,
                    )
                )
            return tuple(entries)
        finally:
            active_error = sys.exc_info()[1]
            try:
                released = lock.release()
                if not released:
                    raise RuntimeError(f"Failed to release library lock: {lock.path}")
            except BaseException as release_error:
                if active_error is None:
                    raise
                detail = (
                    f"quarantine lock release: {type(release_error).__name__}: "
                    f"{release_error}"
                )
                existing = tuple(getattr(active_error, "restore_secondary_errors", ()))
                try:
                    setattr(active_error, "restore_secondary_errors", (*existing, detail))
                    active_error.add_note(f"Restore secondary failure ({detail})")
                except (AttributeError, TypeError):
                    pass

    @classmethod
    def _assert_real_staging_tree(
        cls,
        staging: Path,
        entries: tuple[tuple[str, dict], ...],
    ) -> None:
        """Validate every staging descendant immediately before installation."""
        assert_real_staging_tree(
            staging,
            entries,
            backup_data_root=cls._BACKUP_DATA_ROOT,
        )

    @classmethod
    def _quick_check_database_file(cls, database_file: Path) -> None:
        quick_check_database_file(
            database_file,
            max_database_quick_check_size=cls._MAX_DATABASE_QUICK_CHECK_SIZE,
            quick_check_cache_kib=cls._QUICK_CHECK_CACHE_KIB,
        )

    @classmethod
    def _safe_restore_quarantine_root(
        cls, data_dir: Path, *, create_missing: bool = True
    ) -> Path | None:
        return safe_restore_quarantine_root(data_dir, create_missing=create_missing)

    @classmethod
    def _restore_quarantine_path(cls, data_dir: Path) -> Path:
        return restore_quarantine_path(data_dir)

    @classmethod
    def _move_to_restore_quarantine(
        cls,
        source: Path,
        library_root: Path,
        label: str,
    ) -> Path:
        from AssetsManager.application.library_export_service import (
            library_data_dir,
        )

        data_dir = library_data_dir(library_root)
        runtime_root = data_dir.parent
        cls._assert_real_contained(runtime_root, runtime_root, kind="RuntimeData root directory")
        cls._assert_real_contained(runtime_root, source, kind="Restore quarantine source directory")
        if source.parent.resolve(strict=True) != runtime_root.resolve(strict=True):
            raise ValueError(f"Restore quarantine source is not a direct RuntimeData child: {source}")
        root = cls._safe_restore_quarantine_root(data_dir)
        assert root is not None
        # Re-resolve/recheck the complete destination ancestry immediately before replace.
        cls._assert_real_contained(runtime_root, root, kind="Restore quarantine directory")
        target = root / f"{label}_{source.name}_{uuid.uuid4().hex[:8]}"
        try:
            root.resolve(strict=True).relative_to(runtime_root.resolve(strict=True))
            if cls._is_link_or_junction(root) or cls._is_link_or_junction(root.parent):
                raise ValueError(f"Restore quarantine ancestor changed: {root}")
            source.resolve(strict=True).relative_to(runtime_root.resolve(strict=True))
            if cls._is_link_or_junction(source):
                raise ValueError(f"Refusing to quarantine a link or junction: {source}")
            cls._assert_real_contained(runtime_root, source.parent, kind="Restore quarantine source parent directory")
            cls._assert_real_contained(runtime_root, root, kind="Restore quarantine directory")
            if os.path.lexists(target) and cls._is_link_or_junction(target):
                raise ValueError(f"Restore quarantine target is unsafe: {target}")
            if target.exists():
                raise ValueError(f"Restore quarantine target already exists: {target}")
            source.replace(target)
        except (OSError, RuntimeError, ValueError) as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"Restore quarantine move failed safely: {source}") from exc
        return target
