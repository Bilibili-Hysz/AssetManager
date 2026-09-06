"""Animation engine for FileListGridWidget (fade, hover, selection, entrance).

M0 time-driven model (docs/reports/desktop-motion-direction-2026-09-05.md
§6.2): the QTimer is only a 16 ms beat that requests the next update — every
progression is computed from elapsed monotonic time, never from the number of
callbacks received. ``monotonic`` is a module-level seam so tests can drive a
fake clock. Late or coalesced timer timeouts therefore advance the animations
by the missed time instead of stretching them:

  - thumbnail fade-in : fixed-duration linear ramp (duration converted from
    the old +0.12-per-callback step, see ``_THUMB_FADE_TIER``)
  - hover/selection   : fixed-duration ease-out interpolation toward the
    target; retargeting re-anchors from the currently displayed value (§6.3)
  - entrance stagger  : one batch (size formula unchanged) per elapsed 16 ms
    window; a late tick releases every window it missed

Settle semantics: once elapsed >= duration the value is set exactly to the
terminal state and the per-animation bookkeeping is removed — nothing can
stall at 0.99. The reduce_motion short-circuits, cancellation paths,
generation isolation (``begin_presentation``) and the texture-cache
interaction are unchanged. The widget remains the owner of repaint scheduling
and performance recording via the injected ``on_changed`` callback and the
``host`` reference.
"""
from __future__ import annotations

from time import monotonic, perf_counter
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QTimer

from AssetsManager.core import themes

if TYPE_CHECKING:
    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.panels.file_list._grid_widget import FileListGridWidget


# Nominal cadence of the animation timer (seconds). The timer is only the
# beat; progression derives from elapsed time, so a late timeout releases the
# missed windows instead of stretching the schedule.
_TICK_S = 0.016

# Thumbnail fade-in duration tier. Converted from the previous count-based
# step: +0.12 per 16 ms callback → 1.0 / 0.12 ≈ 8.3 callbacks ≈ 133 ms at the
# nominal cadence. Nearest themes.motion() tier: "micro" (120 ms default).
_THUMB_FADE_TIER = "micro"

# Hover/selection transition duration tier. The previous 0.30-per-callback
# exponential approach had no fixed endpoint (≈13 callbacks ≈ 205 ms until
# |Δ| < 0.01); it is replaced by a fixed-duration ease-out interpolation so
# the completion time is deterministic (§6.2 落定语义). Tier "fast" (150 ms
# default) per the M0 task spec.
_TRANSITION_TIER = "fast"

# Convergence threshold reused from the old damping loops: a (re)anchored
# transition whose start value is already this close to its target settles
# immediately instead of running out the clock.
_SETTLE_EPSILON = 0.01

# A settle counts as "late" (timer stalled) once the elapsed time exceeds the
# nominal duration by this factor. With 16 ms beats the normal worst case is
# duration + 1 tick ≈ 1.13×, so 1.25× keeps ordinary ticking out of the bucket.
_LATE_FACTOR = 1.25


class _Tween:
    """One fixed-duration interpolation between a start value and a target."""

    __slots__ = ("start", "target", "started_at")

    def __init__(self, start: float, target: float, started_at: float) -> None:
        self.start = start
        self.target = target
        self.started_at = started_at

    def value_at(self, now: float, duration_s: float) -> float:
        """Ease-out cubic value at ``now``.

        Ease-out preserves the feel of the old exponential damping (fast
        initial movement, gentle settle) while guaranteeing completion at
        ``started_at + duration_s``.
        """
        p = (now - self.started_at) / duration_s
        p = min(1.0, max(0.0, p))
        return self.start + (self.target - self.start) * (1.0 - (1.0 - p) ** 3)


class Animator:
    """Owns the grid's animation state and time-driven progression."""

    def __init__(
        self,
        parent,
        reduce_motion: bool,
        on_changed: Callable[[set[int]], None],
        host: FileListGridWidget,
    ) -> None:
        self._host = host
        self._on_changed = on_changed
        self._reduce_motion = reduce_motion
        self._thumb_opacity: dict[int, float] = {}
        self._thumb_fade_started: dict[int, float] = {}
        self._thumbnail_rows: set[int] = set()
        self._hover_progress: dict[int, float] = {}
        self._hover_tweens: dict[int, _Tween] = {}
        self._selection_progress: dict[int, float] = {}
        self._selection_tweens: dict[int, _Tween] = {}
        self._anim_timer = QTimer(parent)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._anim_tick)
        self._entrance_queue: list[int] = []
        # bookkeeping-only (V19): written/cleared with the entrance lifecycle
        # but never read by rendering — visibility is derived from
        # ``_thumb_opacity``. Kept because tests assert the write/clear pairs.
        self._entrance_visible: set[int] = set()
        self._entrance_started_at: float | None = None
        self._entrance_batches_done = 0
        self._presented_generation = -1
        self._pending_presentation: tuple[int, list[int], bool] | None = None
        # M0 measurement points (lightweight): the counters are always
        # maintained; an optional PerformanceRecorder receives
        # grid.motion_start / grid.motion_settle events when attached via
        # set_performance_recorder().  Attachment is opt-in: the widget's
        # set_performance_context() does NOT wire it, so no recorder is
        # attached in production yet (stage E doc: 数据可得不接 UI).
        self.motion_stats: dict[str, float] = {
            "started": 0,
            "settled": 0,
            "late_settled": 0,
            "max_late_ms": 0.0,
        }
        self._motion_recorder: PerformanceRecorder | None = None

    # ── Explicit widget-facing API ─────────────────────────────

    @property
    def reduce_motion(self) -> bool:
        return self._reduce_motion

    @property
    def queued_entrance_count(self) -> int:
        return len(self._entrance_queue)

    def has_pending_presentation(self) -> bool:
        """True when a presentation is waiting for the host to become visible."""
        return self._pending_presentation is not None

    def present_pending(self) -> None:
        """Start the most recent presentation queued while the host was hidden."""
        self._present_pending_generation()

    def cancel_entrance(self) -> None:
        """Abort entrance staggering and thumbnail fades (e.g. zoom takeover)."""
        self._entrance_queue.clear()
        self._entrance_visible.clear()
        self._thumb_opacity.clear()
        self._thumb_fade_started.clear()
        self._entrance_started_at = None
        self._entrance_batches_done = 0

    def reanchor_entrance_timeline(self) -> None:
        """Reset the entrance time window so a surviving queue staggers from
        now (V20): a queue that froze mid-zoom keeps its pre-zoom anchor, and
        the next tick would otherwise compute a huge ``batches_due`` and dump
        the whole queue in one burst. Anchoring via ``None`` defers to the
        next tick's clock (same seam the tests drive)."""
        self._entrance_started_at = None
        self._entrance_batches_done = 0

    def reset_for_model_reset(self) -> None:
        """Drop all per-row animation state for a new model generation."""
        self._thumb_opacity.clear()
        self._thumb_fade_started.clear()
        self._thumbnail_rows.clear()
        self._hover_progress.clear()
        self._hover_tweens.clear()
        self._selection_progress.clear()
        self._selection_tweens.clear()
        self._entrance_queue.clear()
        self._entrance_visible.clear()
        self._entrance_started_at = None
        self._entrance_batches_done = 0

    def begin_thumbnail_fade(
        self,
        row: int,
        *,
        has_visible_texture: bool,
        allow_fade: bool,
    ) -> None:
        """Track one replacement texture and seed its fade exactly once."""
        first_track = row not in self._thumbnail_rows
        self._thumbnail_rows.add(row)
        if first_track and not has_visible_texture and not self._reduce_motion and allow_fade:
            self._thumb_opacity[row] = 0.0
            self._thumb_fade_started[row] = monotonic()
            self._record_motion_start("thumbnail", row, self._thumb_fade_duration_s())
            self.ensure_running()

    def ensure_running(self) -> None:
        """Start the 16 ms animation timer when it is not already running."""
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def thumbnail_opacity(self, row: int, default: float = 1.0) -> float:
        return self._thumb_opacity.get(row, default)

    def has_thumbnail_fades(self) -> bool:
        """True while at least one thumbnail fade-in is still in progress."""
        return bool(self._thumb_opacity)

    def hover_progress_value(self, row: int) -> float | None:
        """Return the hover progress for ``row``, or None when not animated."""
        return self._hover_progress.get(row)

    def has_hover_progress(self, row: int) -> bool:
        return row in self._hover_progress

    def selection_progress_value(self, row: int, default: float = 0.0) -> float:
        return self._selection_progress.get(row, default)

    def has_selection_progress(self, row: int) -> bool:
        return row in self._selection_progress

    def setdefault_hover_progress(self, row: int, value: float) -> None:
        """Seed a hover transition (no-op under reduce-motion).

        The tween is anchored at seed time — the transition starts when the
        hover event happens, and a late first tick advances it by the elapsed
        time instead of restarting it.
        """
        if self._reduce_motion or row in self._hover_progress:
            return
        self._hover_progress[row] = value
        target = 1.0 if row == self._host._hover_row else 0.0
        if abs(value - target) <= _SETTLE_EPSILON:
            return
        self._hover_tweens[row] = _Tween(value, target, monotonic())
        self._record_motion_start("hover", row, self._transition_duration_s())

    def setdefault_selection_progress(self, row: int, value: float) -> None:
        """Seed a selection transition (no-op under reduce-motion)."""
        if self._reduce_motion or row in self._selection_progress:
            return
        self._selection_progress[row] = value
        if abs(value) <= _SETTLE_EPSILON:
            return
        self._selection_tweens[row] = _Tween(value, 0.0, monotonic())
        self._record_motion_start("selection", row, self._transition_duration_s())

    def begin_presentation(self, generation: int, visible_rows: list[int], animate: bool = True) -> bool:
        """Commit one content generation and optionally start its one-shot entrance."""
        host = self._host
        if generation <= self._presented_generation or (
            self._pending_presentation is not None and generation <= self._pending_presentation[0]
        ):
            return False
        if not host.isVisible() or host.width() == 0 or host.height() == 0:
            self._pending_presentation = (generation, list(visible_rows), animate)
            return True
        self._start_presentation(generation, visible_rows, animate)
        return True

    def _present_pending_generation(self) -> None:
        host = self._host
        pending = self._pending_presentation
        if pending is None or not host.isVisible() or host.width() == 0 or host.height() == 0:
            return
        self._pending_presentation = None
        self._start_presentation(*pending)

    def discard_pending_presentation(self, generation: int) -> None:
        """Discard a hidden presentation superseded by an empty newer commit."""
        if self._pending_presentation is not None and self._pending_presentation[0] <= generation:
            self._pending_presentation = None

    def _start_presentation(self, generation: int, visible_rows: list[int], animate: bool) -> None:
        self._presented_generation = generation
        self._entrance_queue.clear()
        self._entrance_visible.clear()
        if self._reduce_motion or not animate:
            self._entrance_started_at = None
            self._entrance_batches_done = 0
            return
        self._entrance_queue.extend(row for row in visible_rows if 0 <= row < self._host._model_rows)
        if self._entrance_queue:
            # The stagger window starts when the presentation commits; a late
            # first tick releases every window that already elapsed.
            self._entrance_started_at = monotonic()
            self._entrance_batches_done = 0
            if not self._anim_timer.isActive():
                self._anim_timer.start()

    def apply_selection_progress(self, old_selection: set[int]) -> None:
        """Seed deselected rows for the selection overlay fade-out."""
        if self._reduce_motion:
            return
        for r in old_selection - self._host._selection:
            self._selection_progress[r] = 1.0
            # A re-deselected row restarts its fade from 1.0 (matches the old
            # overwrite), so the tween is re-anchored rather than reused.
            self._selection_tweens[r] = _Tween(1.0, 0.0, monotonic())
            self._record_motion_start("selection", r, self._transition_duration_s())
        if self._selection_progress and not self._anim_timer.isActive():
            self._anim_timer.start()

    def stop(self) -> None:
        """Cancel timer and queued entrance state before teardown."""
        self._anim_timer.stop()
        self._entrance_queue.clear()
        self._entrance_visible.clear()
        self._pending_presentation = None
        self._entrance_started_at = None
        self._entrance_batches_done = 0

    # ── M0 measurement points (lightweight) ────────────────────

    def set_performance_recorder(self, recorder: PerformanceRecorder | None) -> None:
        """Attach the optional motion-metrics sink (no UI wiring).

        Expects the grid's ``PerformanceRecorder`` interface
        (``record(name, elapsed_ms, *, session_token, generation, attributes)``);
        session/generation context is read from the host widget at emit time.
        The counters in :attr:`motion_stats` are maintained whether or not a
        recorder is attached. Recorder failures are swallowed: diagnostics
        must never affect animation state.
        """
        self._motion_recorder = recorder

    def _record_motion_start(self, kind: str, row: int, duration_s: float) -> None:
        self.motion_stats["started"] += 1
        self._emit_motion_event(
            "grid.motion_start",
            0.0,
            {"kind": kind, "row": row, "duration_ms": duration_s * 1000.0},
        )

    def _record_motion_settle(self, kind: str, row: int, duration_s: float, elapsed_s: float) -> None:
        late = elapsed_s > duration_s * _LATE_FACTOR
        stats = self.motion_stats
        stats["settled"] += 1
        if late:
            stats["late_settled"] += 1
            late_ms = (elapsed_s - duration_s) * 1000.0
            if late_ms > stats["max_late_ms"]:
                stats["max_late_ms"] = late_ms
        self._emit_motion_event(
            "grid.motion_settle",
            max(0.0, elapsed_s * 1000.0),
            {"kind": kind, "row": row, "duration_ms": duration_s * 1000.0, "late": late},
        )

    def _emit_motion_event(self, name: str, elapsed_ms: float, attributes: dict) -> None:
        recorder = self._motion_recorder
        if recorder is None:
            return
        try:
            recorder.record(
                name,
                elapsed_ms,
                session_token=getattr(self._host, "_performance_session_token", None),
                generation=getattr(self._host, "_performance_generation", None),
                attributes=attributes,
            )
        except Exception:
            # Diagnostics must not affect paint, animation, or timer state.
            pass

    @staticmethod
    def _thumb_fade_duration_s() -> float:
        return max(0.001, themes.motion(_THUMB_FADE_TIER) / 1000.0)

    @staticmethod
    def _transition_duration_s() -> float:
        return max(0.001, themes.motion(_TRANSITION_TIER) / 1000.0)

    # ── Time-driven progression (M0) ───────────────────────────

    def _anim_tick(self):
        """Process all animations: fade, hover, selection, entrance stagger.

        One monotonic ``now`` per tick; every progression below is a function
        of elapsed time, so late or coalesced timer timeouts advance the
        animations by the missed time instead of stretching them.
        """
        host = self._host
        now = monotonic()
        recorder = host._performance_recorder
        started = perf_counter() if recorder is not None else None
        session_token = host._performance_session_token
        generation = host._performance_generation
        active = False
        changed_rows: set[int] = set()

        if self._reduce_motion and self._hover_progress:
            changed_rows.update(self._hover_progress)
            self._hover_progress.clear()
            self._hover_tweens.clear()

        if self._tick_thumbnail_fades(now, changed_rows):
            active = True
        if self._tick_hover(now, changed_rows):
            active = True
        if self._tick_selection(now, changed_rows):
            active = True
        if self._tick_entrance(now, changed_rows):
            active = True

        if not active:
            self._anim_timer.stop()
        self._on_changed(changed_rows)
        visible_count = 0
        if recorder is not None and host._layout is not None:
            visible_count = len(host._layout.visible_rows(host._scroll_y, host.height()))
        host._record_performance("grid.animation_tick", started, session_token, generation, visible_count)

    def _tick_thumbnail_fades(self, now: float, changed_rows: set[int]) -> bool:
        """Thumbnail fade-in: fixed-duration linear ramp from the anchor time."""
        if not self._thumb_opacity:
            return False
        duration_s = self._thumb_fade_duration_s()
        for row in list(self._thumb_opacity):
            started_at = self._thumb_fade_started.get(row)
            value = self._thumb_opacity[row]
            if started_at is None:
                # Externally seeded progress (tests / programmatic pokes):
                # anchor the timeline so the displayed value is preserved and
                # the fade completes in the remaining time.
                started_at = now - min(max(value, 0.0), 1.0) * duration_s
                self._thumb_fade_started[row] = started_at
            elapsed_s = now - started_at
            changed_rows.add(row)
            if elapsed_s >= duration_s:
                # Settle exactly: the entry is removed and the opacity
                # falls back to the renderer default (1.0).
                del self._thumb_opacity[row]
                self._thumb_fade_started.pop(row, None)
                self._record_motion_settle("thumbnail", row, duration_s, elapsed_s)
            else:
                self._thumb_opacity[row] = elapsed_s / duration_s
        return bool(self._thumb_opacity)

    def _tick_hover(self, now: float, changed_rows: set[int]) -> bool:
        """Hover transitions: fixed-duration ease-out toward the hover target."""
        if not self._hover_progress:
            return False
        host = self._host
        duration_s = self._transition_duration_s()
        active = False
        for row in list(self._hover_progress):
            target = 1.0 if row == host._hover_row else 0.0
            cur = self._hover_progress[row]
            tween = self._hover_tweens.get(row)
            if tween is None or tween.target != target:
                # (Re)anchor from the currently displayed value when a
                # transition begins or the target changed mid-flight (§6.3:
                # resume from the displayed value, never from the old start).
                if abs(cur - target) <= _SETTLE_EPSILON:
                    self._hover_tweens.pop(row, None)
                    self._settle_hover(row, target)
                    changed_rows.add(row)
                    continue
                tween = _Tween(cur, target, now)
                self._hover_tweens[row] = tween
                self._record_motion_start("hover", row, duration_s)
            elapsed_s = now - tween.started_at
            if elapsed_s >= duration_s:
                self._hover_tweens.pop(row, None)
                self._settle_hover(row, target)
                changed_rows.add(row)
                self._record_motion_settle("hover", row, duration_s, elapsed_s)
                continue
            self._hover_progress[row] = tween.value_at(now, duration_s)
            active = True
            changed_rows.add(row)
        return active

    def _settle_hover(self, row: int, target: float) -> None:
        if target == 0.0:
            self._hover_progress.pop(row, None)
        else:
            self._hover_progress[row] = 1.0

    def _tick_selection(self, now: float, changed_rows: set[int]) -> bool:
        """Selection fade-out: fixed-duration ease-out toward 0.0."""
        if not self._selection_progress:
            return False
        duration_s = self._transition_duration_s()
        active = False
        for row in list(self._selection_progress):
            cur = self._selection_progress[row]
            tween = self._selection_tweens.get(row)
            if tween is None:
                if abs(cur) <= _SETTLE_EPSILON:
                    del self._selection_progress[row]
                    changed_rows.add(row)
                    continue
                tween = _Tween(cur, 0.0, now)
                self._selection_tweens[row] = tween
                self._record_motion_start("selection", row, duration_s)
            elapsed_s = now - tween.started_at
            if elapsed_s >= duration_s:
                del self._selection_progress[row]
                self._selection_tweens.pop(row, None)
                changed_rows.add(row)
                self._record_motion_settle("selection", row, duration_s, elapsed_s)
                continue
            self._selection_progress[row] = tween.value_at(now, duration_s)
            active = True
            changed_rows.add(row)
        return active

    def _tick_entrance(self, now: float, changed_rows: set[int]) -> bool:
        """Entrance stagger: one batch per elapsed 16 ms window.

        The batch-size formula (``max(1, len // 12)``) is unchanged; the
        number of batches released on a tick equals the number of 16 ms
        windows elapsed since the entrance began, so a late or coalesced
        timer releases the missed windows at once instead of stretching the
        reveal, and the total stagger no longer depends on callback counts.
        """
        if not self._entrance_queue:
            return False
        host = self._host
        if self._entrance_started_at is None:
            # Queue seeded directly (tests / programmatic): anchor now.
            self._entrance_started_at = now
            self._entrance_batches_done = 0
        if host._zoom_relayout_active:
            # Zoom owns the visual timeline; the queue freezes (preserved
            # quirk: it resumes when the timer restarts after the zoom).
            return False
        elapsed_slots = int((now - self._entrance_started_at) / _TICK_S)
        batches_due = elapsed_slots - self._entrance_batches_done
        if self._entrance_batches_done == 0:
            # The first processed tick always releases one batch (matches the
            # previous per-callback release and keeps tiny queues moving).
            batches_due = max(1, batches_due)
        if batches_due > 0:
            n = max(1, len(self._entrance_queue) // 12)
            release = min(len(self._entrance_queue), batches_due * n)
            fade_duration_s = self._thumb_fade_duration_s()
            for _ in range(release):
                r = self._entrance_queue.pop(0)
                self._entrance_visible.add(r)
                self._thumb_opacity[r] = 0.0
                self._thumb_fade_started[r] = now
                self._record_motion_start("thumbnail", r, fade_duration_s)
                changed_rows.add(r)
            self._entrance_batches_done += batches_due
        return True
