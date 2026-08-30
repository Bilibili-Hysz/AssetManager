"""Gallery incremental-update mixin: apply FileSystemChanged events in place.

Owns the pending-event queue, debounce, snapshot mutation and re-composition
of the cached home.  Members owned by ``GalleryService`` and the other mixins
are declared as class-level annotations so pyright can resolve ``self.*``
attribute access on this mixin without a runtime import cycle.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from AssetsManager.application.app_settings_provider import get_app_settings
from AssetsManager.application.context import ConnectionProvider
from AssetsManager.application.project_service import ProjectDepthConfig
from AssetsManager.core.format_utils import format_size
from AssetsManager.domain.asset import assert_under_root
from AssetsManager.domain.errors import PathEscapeError
from AssetsManager.domain.events import FileSystemChanged

from AssetsManager.application.gallery._types import (
    GalleryHome,
    GalleryTraversalLimits,
    GalleryTraversalLimitError,
    _HomeState,
    _ImageRef,
    _IncrementalFallback,
    _log,
    _QueuedChange,
    _SAFE_GALLERY_IMAGE_EXTS,
    _StateNode,
    _TraversalBudget,
)


class _GalleryIncrementalMixin:
    _MAX_PENDING_EVENTS = 500

    # ── Members owned by GalleryService (__init__/facade) ──────────────
    # Declared as class-level annotations so pyright can resolve self.* on
    # this mixin; at runtime these are set on the concrete GalleryService.
    _closed: bool = False
    _home_cache_lock: threading.Lock
    _home_cache: dict[str, tuple[float, GalleryHome]]
    _home_states: dict[str, _HomeState]
    _generation_lock: threading.Lock
    _home_generation: int
    _pending_lock: threading.Lock
    _pending_events: dict[str, list[_QueuedChange]]
    _build_lock: threading.Lock
    _worker_threads: set[threading.Thread]
    _refresh_timer: threading.Timer | None
    _refresh_timer_root: str | None
    _home_cache_ttl: float
    _inc_timer: threading.Timer | None
    _incremental_debounce: float
    _building: set[str]
    _incremental_applied: int
    _incremental_fallbacks: int
    _connection_provider: ConnectionProvider | None
    _limits: GalleryTraversalLimits
    _depth_config_override: ProjectDepthConfig | None
    _tag_service: Any

    # ── Members owned by GalleryService / other mixins ─────────────────
    _ensure_home_building: Callable[..., None]
    _persist_repository: Callable[[str], Any]
    _save_persisted_projection: Callable[[str, GalleryHome], None]
    _connection: Callable[..., sqlite3.Connection | None]
    _normalize_relative_path: Callable[..., str]
    _build_project_node: Callable[..., dict[str, Any] | None]
    _build_node: Callable[..., dict[str, Any] | None]
    _describe_image: Callable[..., dict[str, Any] | None]

    def _on_file_system_changed(self, event: FileSystemChanged) -> None:
        """Queue library changes for incremental application, falling back
        to the full rebuild semantics when no snapshot is available."""
        if event.kind in {"gallery"}:
            return
        root_key = str(Path(event.library_root).resolve())
        with self._home_cache_lock:
            has_state = root_key in self._home_states and root_key in self._home_cache
        if not has_state:
            # No snapshot: run the historical full-rebuild invalidation.
            self._invalidate_and_schedule_full(root_key)
            return
        with self._generation_lock:
            self._home_generation += 1
            seq = self._home_generation
        with self._pending_lock:
            queue = self._pending_events.setdefault(root_key, [])
            queue.append(_QueuedChange(
                event.kind, tuple(event.paths), tuple(event.old_paths), seq,
            ))
            if len(queue) > self._MAX_PENDING_EVENTS:
                # Queue overflow: fall back to the full rebuild semantics.
                self._pending_events.pop(root_key, None)
                overflow = True
            else:
                overflow = False
        if overflow:
            self._invalidate_and_schedule_full(root_key)
            return
        self._schedule_incremental_apply(root_key)

    @staticmethod
    def _cancel_opposing_changes(
        changes: list[_QueuedChange]
    ) -> list[_QueuedChange]:
        """Collapse bursts that net out before applying them.

        created(P)-then-deleted(P) cancels both (net zero against the
        snapshot); a move round-trip A->B then B->A cancels; a move chain
        A->B then B->C folds into A->C. Multi-path batch events pass
        through untouched.
        """
        result: list[_QueuedChange] = []
        for change in changes:
            if len(change.paths) != 1:
                result.append(change)
                continue
            path = change.paths[0]
            if change.kind == "deleted":
                for i in range(len(result) - 1, -1, -1):
                    prev = result[i]
                    if (
                        prev.kind in {"created", "copied", "restored"}
                        and prev.paths and prev.paths[0] == path
                    ):
                        result.pop(i)
                        break
                else:
                    result.append(change)
            elif change.kind == "moved" and len(change.old_paths) == 1:
                src, dst = change.old_paths[0], path
                cancelled = False
                for i in range(len(result) - 1, -1, -1):
                    prev = result[i]
                    if (
                        prev.kind == "moved" and len(prev.old_paths) == 1
                        and prev.paths[0] == src and prev.old_paths[0] == dst
                    ):
                        # Round-trip A->B then B->A: net zero.
                        result.pop(i)
                        cancelled = True
                        break
                if not cancelled:
                    for i in range(len(result) - 1, -1, -1):
                        prev = result[i]
                        if (
                            prev.kind == "moved" and len(prev.old_paths) == 1
                            and prev.paths[0] == src
                        ):
                            # Chain A->B then B->C folds to A->C.
                            result[i] = _QueuedChange(
                                "moved", (dst,), prev.old_paths, change.seq,
                            )
                            break
                    else:
                        result.append(change)
            else:
                result.append(change)
        return result

    def _invalidate_and_schedule_full(self, root_key: str) -> None:
        """Drop the cached/state/persisted projection and schedule a full
        rebuild (debounced so a burst of events rebuilds once).

        The rebuild runs on a fixed deadline: the timer armed by the first
        invalidate is kept across later invalidates for the same root, so a
        sustained event stream in the no-snapshot window cannot push the
        rebuild out forever (TTL semantics — when the rebuild eventually
        runs it just re-walks the library; debounce semantics live solely
        in ``_schedule_incremental_apply``). A later invalidate for a
        *different* root still replaces the single shared timer, matching
        the historical last-writer-wins behavior.
        """
        if self._closed:
            return
        with self._home_cache_lock:
            self._home_cache.pop(root_key, None)
            self._home_states.pop(root_key, None)
        try:
            self._persist_repository(root_key).delete()
        except Exception:
            _log.debug("Gallery home persisted projection delete failed", exc_info=True)
        with self._build_lock:
            if (
                self._refresh_timer is not None
                and self._refresh_timer_root == root_key
            ):
                # A rebuild for this root is already pending on its fixed
                # deadline: keep it instead of restarting the TTL timer.
                return
            if self._refresh_timer is not None:
                self._refresh_timer.cancel()
                # The replaced timer may have belonged to another root; drop
                # its pending marker so that root can re-arm later.
                self._refresh_timer_root = None
            self._refresh_timer_root = root_key
            self._refresh_timer = threading.Timer(
                self._home_cache_ttl, self._fire_scheduled_full_rebuild,
                args=(root_key,),
            )
            self._refresh_timer.daemon = True
            self._refresh_timer.start()

    def _fire_scheduled_full_rebuild(self, root_key: str) -> None:
        """Timer callback for a scheduled full rebuild: release the fixed
        deadline marker, then kick the (idempotent) background build."""
        with self._build_lock:
            if self._refresh_timer_root == root_key:
                self._refresh_timer_root = None
        if self._closed:
            return
        self._ensure_home_building(root_key)

    def _schedule_incremental_apply(self, root_key: str) -> None:
        """Debounce pending changes into one short apply window."""
        if self._closed:
            return
        with self._build_lock:
            if self._inc_timer is not None:
                self._inc_timer.cancel()
            self._inc_timer = threading.Timer(
                self._incremental_debounce, self._apply_pending_home, args=(root_key,)
            )
            self._inc_timer.daemon = True
            self._inc_timer.start()

    def _apply_pending_home(self, root_key: str) -> None:
        """Apply queued changes incrementally; fall back to a full rebuild
        on any inconsistency, budget overrun, or concurrent full build.

        The timer thread registers itself as an in-flight worker before
        touching anything so ``GalleryService.close()`` can join it and
        guarantee the shared sqlite connection is never used after the
        owning session closed it.
        """
        with self._build_lock:
            if self._closed:
                return
            self._worker_threads.add(threading.current_thread())
        try:
            self._apply_pending_home_impl(root_key)
        finally:
            with self._build_lock:
                self._worker_threads.discard(threading.current_thread())

    def _apply_pending_home_impl(self, root_key: str) -> None:
        if self._closed:
            return
        with self._pending_lock:
            changes = self._pending_events.pop(root_key, None)
        if not changes:
            return
        with self._home_cache_lock:
            state = self._home_states.get(root_key)
            cached = self._home_cache.get(root_key)
        if state is None or cached is None:
            self._invalidate_and_schedule_full(root_key)
            return
        changes = [change for change in changes if change.seq > state.generation]
        changes = self._cancel_opposing_changes(changes)
        if not changes:
            return
        with self._build_lock:
            busy = root_key in self._building
            if not busy:
                self._building.add(root_key)
        if busy:
            # A full rebuild is running; its result supersedes the snapshot.
            # Re-queue briefly instead of racing it. (Scheduling must happen
            # outside _build_lock: _schedule_incremental_apply takes it, and
            # threading.Lock is not reentrant.)
            with self._pending_lock:
                self._pending_events.setdefault(root_key, []).extend(changes)
            self._schedule_incremental_apply(root_key)
            return
        try:
            home = cached[1]
            for change in changes:
                home = self._apply_change(root_key, state, change, home)
            # One recompose per window: the per-event recomposes (a full
            # refs sort plus the 24-image recent decode) ran inside
            # _apply_change before, so a window of k events cost k full
            # passes. No branch consumes the intermediate recompose result
            # (home is only threaded through for the no-op returns), so a
            # single pass after the last state mutation is equivalent.
            root = Path(root_key).resolve()
            conn = self._connection(root, None, self._connection_provider)
            home = self._recompose_home(root, state, conn)
            self._incremental_applied += len(changes)
            with self._home_cache_lock:
                # Watermark: the snapshot now covers exactly this window's
                # events. Never bump the seq counter here — it only issues
                # seqs; advancing it past events queued during this window
                # would make the ``seq > generation`` filter drop them.
                state.generation = max(change.seq for change in changes)
                self._home_cache[root_key] = (time.monotonic(), home)
            self._save_persisted_projection(root_key, home)
        except Exception:
            self._incremental_fallbacks += 1
            _log.info(
                "Incremental gallery apply fell back to a full rebuild "
                "(applied=%d, fallbacks=%d)",
                self._incremental_applied, self._incremental_fallbacks,
                exc_info=True,
            )
            self._invalidate_and_schedule_full(root_key)
        finally:
            with self._build_lock:
                self._building.discard(root_key)

    @property
    def incremental_stats(self) -> tuple[int, int]:
        """Return (applied_event_count, fallback_count) since construction."""
        return self._incremental_applied, self._incremental_fallbacks

    @staticmethod
    def _parent_rel(rel: str) -> str:
        return "/".join(part for part in rel.split("/")[:-1] if part)

    def _rel(self, root: Path, absolute: str) -> str | None:
        """Normalize an absolute event path to a library-relative path."""
        try:
            target = assert_under_root(Path(absolute).resolve(), root)
        except (OSError, PathEscapeError, ValueError):
            return None
        return self._normalize_relative_path(str(target.relative_to(root)))

    def _depth_config(self) -> ProjectDepthConfig:
        """Project depth config (override or live ``sidebar_depth_cfg``)."""
        if self._depth_config_override is not None:
            return self._depth_config_override
        try:
            raw = get_app_settings().get("sidebar_depth_cfg")
            return ProjectDepthConfig.from_dict(raw or {})
        except Exception:
            return ProjectDepthConfig()

    @staticmethod
    def _project_floor(config: ProjectDepthConfig, relative_path: str) -> int:
        """Depth at which directories become project leaves (branch-aware)."""
        branch = relative_path.split("/", 1)[0] if relative_path else ""
        return config.branches.get(branch, config.global_depth)

    def _inside_project(self, relative_path: str) -> bool:
        """Whether *relative_path* is a directory deeper than its project
        floor — i.e. inside a project, where nothing is projected."""
        parts = relative_path.split("/")
        if len(parts) < 2:
            return False
        config = self._depth_config()
        floor = config.branches.get(parts[0], config.global_depth)
        return len(parts) > floor

    def _apply_change(
        self,
        root_key: str,
        state: _HomeState,
        change: _QueuedChange,
        home: GalleryHome,
    ) -> GalleryHome:
        root = Path(root_key).resolve()
        if change.kind in {"created", "copied", "restored"}:
            for path in change.paths:
                try:
                    is_dir = Path(path).is_dir()
                except OSError:
                    is_dir = False
                if is_dir:
                    home = self._apply_dir_event(root, state, home, path, None, "created")
                else:
                    home = self._apply_file_event(root, state, home, path, None, "created")
        elif change.kind == "deleted":
            for path in change.paths:
                rel = self._rel(root, path)
                if (
                    rel is not None
                    and rel not in state.nodes
                    and rel not in state.files
                    and self._inside_project(rel)
                ):
                    # A directory inside a project vanished: it is not in
                    # the state tree (projects aggregate), so the project's
                    # stats cannot be patched incrementally.
                    raise _IncrementalFallback("directory deleted inside a project")
                if rel is not None and rel in state.nodes:
                    home = self._apply_dir_event(root, state, home, path, None, "deleted")
                else:
                    home = self._apply_file_event(root, state, home, path, None, "deleted")
        elif change.kind == "moved":
            # A move event may carry paths without a matching old_path for each
            # (and this runs inside the event loop), so truncate silently.
            for new_path, old_path in zip(change.paths, change.old_paths, strict=False):
                try:
                    is_dir = Path(new_path).is_dir()
                except OSError:
                    is_dir = False
                if is_dir:
                    home = self._apply_dir_event(root, state, home, new_path, old_path, "moved")
                else:
                    home = self._apply_file_event(root, state, home, new_path, old_path, "moved")
        else:
            raise _IncrementalFallback(f"unsupported event kind {change.kind}")
        return home

    @staticmethod
    def _collect_descendants(state: _HomeState, key: str) -> list[str]:
        """Return *key* plus every descendant state key (depth-first)."""
        collected: list[str] = []
        stack = [key]
        while stack:
            current = stack.pop()
            collected.append(current)
            node = state.nodes.get(current)
            if node is not None:
                stack.extend(node.children)
        return collected

    def _apply_dir_event(
        self,
        root: Path,
        state: _HomeState,
        home: GalleryHome,
        new_abs: str,
        old_abs: str | None,
        kind: str,
    ) -> GalleryHome:
        if kind == "created":
            rel = self._rel(root, new_abs)
            if rel is None or not rel:
                raise _IncrementalFallback("directory path escapes the library")
            if rel in state.nodes:
                return home  # idempotent guard
            if self._inside_project(rel):
                # Projects aggregate their whole subtree; a new directory
                # inside one needs a project-level re-aggregation, which the
                # incremental applier does not support — rebuild instead.
                raise _IncrementalFallback("directory created inside a project")
            parent_key = self._parent_rel(rel) or "/"
            parent = state.nodes.get(parent_key)
            if parent is None:
                raise _IncrementalFallback(f"unknown parent {parent_key}")
            # Bounded sub-walk of the new subtree (raises the traversal limit
            # error on runaway trees; the caller falls back to a full build).
            sub_refs: list[_ImageRef] = []
            sub_nodes: dict[str, _StateNode] = {}
            sub_files: dict[str, tuple[int, int]] = {}
            config = self._depth_config()
            try:
                if len(rel.split("/")) == self._project_floor(config, rel):
                    # The new directory sits exactly at the project floor:
                    # aggregate its whole subtree like the full build does,
                    # or nested content would be dropped by the projection.
                    sub_root = self._build_project_node(
                        root, rel, Path(new_abs),
                        include_entries=False,
                        budget=_TraversalBudget(self._limits),
                        depth=len(rel.split("/")),
                        image_refs=sub_refs,
                        node_counts=None,
                        state_nodes=sub_nodes,
                        known_files=sub_files,
                    )
                else:
                    sub_root = self._build_node(
                        root, rel, Path(new_abs),
                        include_entries=False,
                        budget=_TraversalBudget(self._limits),
                        depth=len(rel.split("/")),
                        image_refs=sub_refs,
                        node_counts=None,
                        state_nodes=sub_nodes,
                        known_files=sub_files,
                        project_depth=config,
                    )
            except GalleryTraversalLimitError as exc:
                raise _IncrementalFallback("directory sub-walk exceeded budget") from exc
            if sub_root is None:
                # Empty directories are pruned by the projection: no-op.
                return home
            summary = sub_nodes[rel].summary
            state.nodes.update(sub_nodes)
            state.files.update(sub_files)
            state.refs.extend(sub_refs)
            parent.children.append(rel)
            if parent.summary.get("kind") == "project":
                parent.summary = {**parent.summary, "kind": "collection"}
            self._resort_children(state, parent_key)
            if not parent.direct_images:
                # The cover comes from the (re-sorted) children: the new
                # project may now be the first child with a cover.
                self._recompute_cover(root, state, parent_key)
            self._bump_ancestors(
                state, parent_key,
                size_delta=int(summary["size"]),
                file_delta=int(summary["file_count"]),
                artwork_delta=int(summary["artwork_count"]),
                modified_candidate=int(summary["modified"]),
                child_delta=1,
            )
            return home

        if kind == "deleted":
            rel = self._rel(root, new_abs)
            if rel is None or not rel or rel not in state.nodes:
                return home  # unknown or already applied
            node = state.nodes[rel]
            summary = node.summary
            parent_key = self._parent_rel(rel) or "/"
            parent = state.nodes.get(parent_key)
            if parent is None:
                raise _IncrementalFallback(f"unknown parent {parent_key}")
            parent_sole_content = (
                int(parent.summary["file_count"]) == int(summary["file_count"])
                and len(parent.children) == 1
            )
            if (
                not parent_sole_content
                and int(parent.summary["modified"]) == int(summary["modified"])
            ):
                raise _IncrementalFallback("deleted directory carried the max mtime")
            descendants = self._collect_descendants(state, rel)
            for key in descendants:
                state.nodes.pop(key, None)
            prefix = rel + "/"
            state.files = {
                path: entry for path, entry in state.files.items()
                if not path.startswith(prefix)
            }
            state.refs = [ref for ref in state.refs if not ref.path.startswith(prefix)]
            state.image_paths = {path for path in state.image_paths if not path.startswith(prefix)}
            parent.children.remove(rel)
            if not parent.direct_images:
                # The cover came from the children: recompute it so a
                # deleted child's cover cannot leave it dangling.
                self._recompute_cover(root, state, parent_key)
            self._bump_ancestors(
                state, parent_key,
                size_delta=-int(summary["size"]),
                file_delta=-int(summary["file_count"]),
                artwork_delta=-int(summary["artwork_count"]),
                modified_candidate=-1,
                child_delta=-1,
            )
            survivor = self._prune_empty_chain(root, state, parent_key)
            if (
                survivor in state.nodes
                and survivor != parent_key
                and int(state.nodes[survivor].summary["modified"]) == int(summary["modified"])
            ):
                # The deleted subtree carried the survivor's max mtime and
                # the intermediate chain was pruned: recompute the mtime
                # from the survivor's own directory instead of rebuilding.
                self._recompute_modified(root, state, survivor)
            return home

        if kind == "moved" and old_abs is not None:
            rel_old = self._rel(root, old_abs)
            rel_new = self._rel(root, new_abs)
            if rel_old is None or rel_new is None or not rel_old or not rel_new:
                raise _IncrementalFallback("directory move escapes the library")
            if rel_old == rel_new:
                return home
            if rel_old not in state.nodes:
                raise _IncrementalFallback("moved source directory unknown")
            if rel_new in state.nodes:
                raise _IncrementalFallback("moved destination directory already known")
            if self._parent_rel(rel_old) == self._parent_rel(rel_new):
                # Same-parent rename: rewrite the subtree keys in place.
                keys = self._collect_descendants(state, rel_old)
                for key in keys:
                    new_key = rel_new + key[len(rel_old):]
                    moved_node = state.nodes.pop(key)
                    moved_summary = {
                        **moved_node.summary,
                        "path": new_key,
                        "name": new_key.rsplit("/", 1)[-1],
                        "parent_path": self._parent_rel(new_key),
                    }
                    cover = moved_node.summary.get("cover_path")
                    if cover:
                        moved_summary["cover_path"] = rel_new + cover[len(rel_old):]
                    moved_node.summary = moved_summary
                    moved_node.direct_images = [
                        rel_new + path[len(rel_old):] for path in moved_node.direct_images
                    ]
                    moved_node.children = [
                        rel_new + path[len(rel_old):] for path in moved_node.children
                    ]
                    state.nodes[new_key] = moved_node
                state.files = {
                    (
                        rel_new + path[len(rel_old):]
                        if path == rel_old or path.startswith(rel_old + "/")
                        else path
                    ): entry
                    for path, entry in state.files.items()
                }
                state.refs = [
                    _ImageRef(rel_new + ref.path[len(rel_old):], ref.modified)
                    if ref.path == rel_old or ref.path.startswith(rel_old + "/")
                    else ref
                    for ref in state.refs
                ]
                # Rebuild image_paths set from updated refs
                state.image_paths = {ref.path for ref in state.refs}
                parent_key = self._parent_rel(rel_old) or "/"
                parent = state.nodes.get(parent_key)
                if parent is None:
                    raise _IncrementalFallback("moved parent unknown")
                parent.children = [
                    rel_new if path == rel_old else path for path in parent.children
                ]
                # Re-describe covers for the moved node and every ancestor:
                # their cover_paths may have pointed into the renamed subtree.
                cover_keys = [rel_new]
                key = parent_key
                while True:
                    cover_keys.append(key)
                    if key == "/":
                        break
                    key = self._parent_rel(key) or "/"
                for key in cover_keys:
                    if key in state.nodes:
                        self._recompute_cover(root, state, key)
                self._resort_children(state, parent_key)
                return home

            # Cross-parent move: delete from the old parent, then sub-walk
            # the destination (both guarded; any inconsistency falls back).
            home = self._apply_dir_event(root, state, home, old_abs, None, "deleted")
            return self._apply_dir_event(root, state, home, new_abs, None, "created")

        raise _IncrementalFallback(f"unsupported directory event {kind}")

    def _recompute_modified(self, root: Path, state: _HomeState, key: str) -> None:
        """Recompute a node's max mtime from its direct files and children.

        Used after a deletion pruned an intermediate chain: the node's
        summary may still carry the deleted item's mtime (bump_ancestors
        never decreases), and re-walking just this one directory is cheap
        and exact — unlike falling back to a full rebuild.
        """
        node = state.nodes.get(key)
        if node is None:
            raise _IncrementalFallback(f"missing node {key}")
        target = root if key == "/" else root / key
        latest = 0
        try:
            with os.scandir(target) as iterator:
                for entry in iterator:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            stat_result = entry.stat(follow_symlinks=False)
                            latest = max(latest, int(stat_result.st_mtime))
                    except OSError:
                        continue
        except OSError:
            pass
        for child in node.children:
            child_node = state.nodes.get(child)
            if child_node is not None:
                latest = max(latest, int(child_node.summary["modified"]))
        node.summary = {**node.summary, "modified": latest}

    def _prune_empty_chain(
        self, root: Path, state: _HomeState, start_key: str
    ) -> str:
        """Remove nodes that became empty (no files, no child dirs),
        matching the build's pruning rule, cascading up to the root.

        Returns the first ancestor key that survived (``start_key`` itself
        when it was not pruned).  When a node is pruned, the parent's cover
        is recomputed if it pointed into the pruned subtree, so a deleted
        child cover never leaves a dangling ``cover_path`` behind.
        """
        key = start_key
        while key != "/":
            node = state.nodes.get(key)
            if node is None or node.children or int(node.summary["file_count"]) > 0:
                # Not empty: only the kind may have flipped.
                if node is not None and not node.children:
                    node.summary = {**node.summary, "kind": "project"}
                return key
            parent_key = self._parent_rel(key) or "/"
            parent = state.nodes.get(parent_key)
            if parent is None:
                raise _IncrementalFallback(f"missing parent {parent_key}")
            state.nodes.pop(key, None)
            if key in parent.children:
                parent.children.remove(key)
            cover = parent.summary.get("cover_path")
            if cover and str(cover).startswith(key + "/"):
                self._recompute_cover(root, state, parent_key)
            key = parent_key
        return "/"

    def _apply_file_event(
        self,
        root: Path,
        state: _HomeState,
        home: GalleryHome,
        new_abs: str,
        old_abs: str | None,
        kind: str,
    ) -> GalleryHome:
        if kind == "created":
            rel = self._rel(root, new_abs)
            if rel is None:
                raise _IncrementalFallback("created path escapes the library")
            if rel in state.files:
                return home  # idempotent guard: already applied
            target = Path(new_abs)
            try:
                if target.is_dir():
                    raise _IncrementalFallback("directory events are not incremental yet")
                st = target.stat()
            except OSError as exc:
                raise _IncrementalFallback("cannot stat created path") from exc
            is_image = target.suffix.lower() in _SAFE_GALLERY_IMAGE_EXTS
            parent_key = self._parent_rel(rel) or "/"
            parent = state.nodes.get(parent_key)
            if parent is None:
                raise _IncrementalFallback(f"unknown parent {parent_key}")
            state.files[rel] = (int(st.st_size), int(st.st_mtime))
            if is_image:
                state.refs.append(_ImageRef(rel, int(st.st_mtime)))
                parent.direct_images.append(rel)
                parent.direct_images.sort(key=lambda path: path.casefold())
                if parent.summary.get("cover_path") is None or parent.direct_images[0] == rel:
                    self._recompute_cover(root, state, parent_key)
            self._bump_ancestors(
                state, parent_key,
                size_delta=int(st.st_size),
                file_delta=1,
                artwork_delta=1 if is_image else 0,
                modified_candidate=int(st.st_mtime),
            )
            return home

        if kind == "deleted":
            rel = self._rel(root, new_abs)
            if rel is None or rel not in state.files:
                return home  # unknown or already applied
            size, mtime = state.files.pop(rel)
            parent_key = self._parent_rel(rel) or "/"
            parent = state.nodes.get(parent_key)
            if parent is None:
                raise _IncrementalFallback(f"unknown parent {parent_key}")
            parent_sole_content = int(parent.summary["file_count"]) == 1 and not parent.children
            if not parent_sole_content and int(parent.summary["modified"]) == mtime:
                # The subtree maximum left with this file; we cannot compute
                # the next maximum without re-walking. (When it is the
                # parent's only content the parent is pruned instead, so the
                # maximum is irrelevant.)
                raise _IncrementalFallback("deleted file carried the max mtime")
            is_image = rel in state.image_paths
            if is_image:
                state.refs = [ref for ref in state.refs if ref.path != rel]
                state.image_paths.discard(rel)
                if rel in parent.direct_images:
                    parent.direct_images.remove(rel)
                if parent.summary.get("cover_path") == rel:
                    self._recompute_cover(root, state, parent_key)
            self._bump_ancestors(
                state, parent_key,
                size_delta=-size,
                file_delta=-1,
                artwork_delta=-1 if is_image else 0,
                modified_candidate=-1,
            )
            survivor = self._prune_empty_chain(root, state, parent_key)
            if (
                survivor in state.nodes
                and survivor != parent_key
                and int(state.nodes[survivor].summary["modified"]) == mtime
            ):
                # The chain above the parent was pruned and the survivor's
                # max mtime was this file's: recompute it from the
                # survivor's own directory (cheap, exact).
                self._recompute_modified(root, state, survivor)
            return home

        if kind == "moved" and old_abs is not None:
            rel_old = self._rel(root, old_abs)
            rel_new = self._rel(root, new_abs)
            if rel_old is None or rel_new is None:
                raise _IncrementalFallback("moved path escapes the library")
            if rel_old == rel_new:
                return home
            if rel_old not in state.files:
                raise _IncrementalFallback("moved source unknown")
            if rel_new in state.files:
                raise _IncrementalFallback("moved destination already known")
            target = Path(new_abs)
            try:
                if target.is_dir():
                    raise _IncrementalFallback("directory moves are not incremental yet")
                st = target.stat()
            except OSError as exc:
                raise _IncrementalFallback("cannot stat moved target") from exc
            size, old_mtime = state.files.pop(rel_old)
            state.files[rel_new] = (int(st.st_size), int(st.st_mtime))
            is_image = rel_old in state.image_paths
            if is_image:
                state.refs = [
                    ref if ref.path != rel_old else _ImageRef(rel_new, ref.modified)
                    for ref in state.refs
                ]
                state.image_paths.discard(rel_old)
                state.image_paths.add(rel_new)
            old_parent_key = self._parent_rel(rel_old) or "/"
            new_parent_key = self._parent_rel(rel_new) or "/"
            old_parent = state.nodes.get(old_parent_key)
            new_parent = state.nodes.get(new_parent_key)
            if old_parent is None or new_parent is None:
                raise _IncrementalFallback("moved parent unknown")
            old_sole_content = int(old_parent.summary["file_count"]) == 1 and not old_parent.children
            if not old_sole_content and int(old_parent.summary["modified"]) == old_mtime:
                raise _IncrementalFallback("moved file carried the old max mtime")
            if is_image and rel_old in old_parent.direct_images:
                old_parent.direct_images.remove(rel_old)
                if old_parent.summary.get("cover_path") == rel_old:
                    self._recompute_cover(root, state, old_parent_key)
            if is_image:
                new_parent.direct_images.append(rel_new)
                new_parent.direct_images.sort(key=lambda path: path.casefold())
                if new_parent.summary.get("cover_path") is None or new_parent.direct_images[0] == rel_new:
                    self._recompute_cover(root, state, new_parent_key)
            self._bump_ancestors(
                state, old_parent_key,
                size_delta=-size,
                file_delta=-1,
                artwork_delta=-1 if is_image else 0,
                modified_candidate=-1,
            )
            survivor = self._prune_empty_chain(root, state, old_parent_key)
            if (
                survivor in state.nodes
                and survivor != old_parent_key
                and int(state.nodes[survivor].summary["modified"]) == old_mtime
            ):
                self._recompute_modified(root, state, survivor)
            self._bump_ancestors(
                state, new_parent_key,
                size_delta=int(st.st_size),
                file_delta=1,
                artwork_delta=1 if is_image else 0,
                modified_candidate=int(st.st_mtime),
            )
            return home

        raise _IncrementalFallback(f"unsupported event {kind}")

    def _bump_ancestors(
        self,
        state: _HomeState,
        start_key: str,
        *,
        size_delta: int,
        file_delta: int,
        artwork_delta: int,
        modified_candidate: int,
        child_delta: int = 0,
    ) -> None:
        """Propagate aggregate deltas from *start_key* up to the root.

        Each summary is replaced wholesale (never mutated in place) so the
        LAN route thread serializing the cached home never observes torn
        key/value pairs mid-apply.
        """
        parts = [part for part in start_key.split("/") if part]
        touched: list[str] = []
        for i in range(len(parts), -1, -1):
            key = "/".join(parts[:i]) or "/"
            node = state.nodes.get(key)
            if node is None:
                raise _IncrementalFallback(f"missing node {key}")
            summary = node.summary
            new_summary = dict(summary)
            new_summary["size"] = max(0, int(summary["size"]) + size_delta)
            new_summary["size_fmt"] = format_size(int(new_summary["size"]))
            new_summary["file_count"] = max(0, int(summary["file_count"]) + file_delta)
            new_summary["artwork_count"] = max(0, int(summary["artwork_count"]) + artwork_delta)
            new_summary["child_count"] = max(0, int(summary["child_count"]) + child_delta)
            if modified_candidate > int(summary["modified"]):
                new_summary["modified"] = modified_candidate
            node.summary = new_summary
            touched.append(key)
        for key in touched:
            if key == "/":
                continue
            parent_key = self._parent_rel(key) or "/"
            if state.nodes is not None and parent_key in state.nodes:
                self._resort_children(state, parent_key)

    def _resort_children(self, state: _HomeState, parent_key: str) -> None:
        parent = state.nodes.get(parent_key)
        if parent is None:
            raise _IncrementalFallback(f"missing parent {parent_key}")
        parent.children.sort(key=lambda path: (
            -int(state.nodes[path].summary["modified"]),
            str(state.nodes[path].summary["name"]).casefold(),
        ))

    def _recompute_cover(self, root: Path, state: _HomeState, node_key: str) -> None:
        node = state.nodes.get(node_key)
        if node is None:
            raise _IncrementalFallback(f"missing node {node_key}")
        summary = node.summary
        cover_path = (
            node.direct_images[0]
            if node.direct_images
            else next(
                (
                    state.nodes[child].summary.get("cover_path")
                    for child in node.children
                    if state.nodes[child].summary.get("cover_path")
                ),
                None,
            )
        )
        cover = self._describe_image(root, cover_path) if cover_path else None
        # Wholesale replacement (never mutate in place): readers on the LAN
        # route thread must see an atomically consistent summary.
        node.summary = {
            **summary,
            "cover_path": cover_path,
            "width": cover.get("width") if cover else None,
            "height": cover.get("height") if cover else None,
            "aspect_ratio": cover.get("aspect_ratio") if cover else None,
        }

    def _recompose_home(
        self, root: Path, state: _HomeState, db_conn
    ) -> GalleryHome:
        root_node = state.nodes.get("/")
        if root_node is None:
            raise _IncrementalFallback("root state missing")
        children = [
            state.nodes[path].summary for path in root_node.children
            if path in state.nodes
        ]
        collections = [item for item in children if item.get("kind") == "collection"]
        projects = [item for item in children if item.get("kind") == "project"]
        refs = sorted(state.refs, key=lambda item: (-item.modified, item.path.casefold()))
        recent: list[dict[str, Any]] = []
        for ref in refs[:24]:
            described = self._describe_image(root, ref.path)
            if described:
                recent.append(described)
        self._apply_tags_to_entries(root, recent, db_conn=db_conn)
        # The build counts every non-root node by kind, not just the
        # root's direct children.
        collections_count = sum(
            1 for key, entry in state.nodes.items()
            if key != "/" and entry.summary.get("kind") == "collection"
        )
        projects_count = sum(
            1 for key, entry in state.nodes.items()
            if key != "/" and entry.summary.get("kind") == "project"
        )
        stats = {
            "collections": collections_count,
            "projects": projects_count,
            "artworks": int(root_node.summary["artwork_count"]),
            "total_size_fmt": str(root_node.summary["size_fmt"]),
        }
        featured = collections[0] if collections else projects[0] if projects else root_node.summary
        return GalleryHome(featured, collections, projects, recent, stats)

    def _apply_tags(
        self,
        root: Path,
        node: dict[str, Any] | None,
        *,
        db_conn: sqlite3.Connection | None,
        extra_entries: Iterable[dict[str, Any]] = (),
    ) -> None:
        if node is None:
            return
        paths: list[str] = []
        seen: set[str] = set()

        def add_path(path: str) -> None:
            if path not in seen:
                seen.add(path)
                paths.append(path)

        def collect(current: dict[str, Any]) -> None:
            add_path(str(current["path"]))
            for child in current.get("children", ()):
                collect(child)
            for entry in current.get("entries", ()):
                add_path(str(entry["path"]))

        collect(node)
        for entry in extra_entries:
            add_path(str(entry["path"]))
        if not paths:
            return
        try:
            tags_by_path = self._tag_service.get_tags_for_files(
                root, [root / path for path in paths], db_conn=db_conn
            )
        except (RuntimeError, sqlite3.Error, ValueError):
            _log.debug("Gallery tag projection unavailable", exc_info=True)
            tags_by_path = {}

        def tags_for(relative_path: str) -> list[str]:
            key = str((root / relative_path).resolve())
            return list(tags_by_path.get(key, ()))

        def apply(current: dict[str, Any]) -> None:
            current["tags"] = tags_for(str(current["path"]))
            for child in current.get("children", ()):
                apply(child)
            for entry in current.get("entries", ()):
                entry["tags"] = tags_for(str(entry["path"]))

        apply(node)
        for entry in extra_entries:
            entry["tags"] = tags_for(str(entry["path"]))

    def _apply_tags_to_entries(
        self,
        root: Path,
        entries: list[dict[str, Any]],
        *,
        db_conn: sqlite3.Connection | None,
    ) -> None:
        if not entries:
            return
        try:
            tags_by_path = self._tag_service.get_tags_for_files(
                root, [root / str(entry["path"]) for entry in entries], db_conn=db_conn
            )
        except (RuntimeError, sqlite3.Error, ValueError):
            _log.debug("Gallery artwork tag projection unavailable", exc_info=True)
            return
        for entry in entries:
            key = str((root / str(entry["path"])).resolve())
            entry["tags"] = list(tags_by_path.get(key, ()))

    @staticmethod
    def _sort_entries(entries: list[dict[str, Any]], sort: str) -> None:
        if sort == "name":
            entries.sort(key=lambda item: str(item["name"]).casefold())
        else:
            entries.sort(key=lambda item: (-int(item["modified"]), str(item["name"]).casefold()))
