"""Tests for opt-in bounded performance diagnostics."""
from __future__ import annotations

import threading
from math import inf, nan

import pytest

from AssetsManager.core.performance import PerformanceRecorder


def test_disabled_recorder_is_noop():
    recorder = PerformanceRecorder()

    recorder.record("directory.list", 12.5, session_token="session-a", path="/library")
    with recorder.measure("thumbnail.decode"):
        pass

    assert recorder.recent() == ()


def test_recorder_keeps_correlation_context_and_immutable_attributes():
    recorder = PerformanceRecorder(enabled=True)
    recorder.record(
        "thumbnail.decode",
        12.5,
        session_token="session-a",
        generation=4,
        path="/library/asset.png",
        attributes={"cache_hit": False, "queue_depth": 3},
    )

    event = recorder.recent()[0]

    assert event.name == "thumbnail.decode"
    assert event.elapsed_ms == 12.5
    assert event.occurred_at > 0
    assert event.session_token == "session-a"
    assert event.generation == 4
    assert event.path == "/library/asset.png"
    assert event.attributes == {"cache_hit": False, "queue_depth": 3}
    with pytest.raises(TypeError):
        event.attributes["cache_hit"] = True  # type: ignore[index]


def test_recorder_clamps_duration_and_bounds_retention():
    recorder = PerformanceRecorder(enabled=True, max_events=2)
    recorder.record("first", -1)
    recorder.record("second", 2)
    recorder.record("third", 3)

    events = recorder.recent()

    assert [event.name for event in events] == ["second", "third"]
    assert recorder.recent(1) == (events[-1],)


def test_measure_records_monotonic_elapsed_time():
    recorder = PerformanceRecorder(enabled=True)

    with recorder.measure("directory.first_screen", session_token="session-a", generation=2):
        pass

    event = recorder.recent()[0]
    assert event.elapsed_ms >= 0
    assert event.session_token == "session-a"
    assert event.generation == 2


def test_recorder_rejects_invalid_configuration_and_event_name():
    with pytest.raises(ValueError, match="max_events"):
        PerformanceRecorder(max_events=0)
    with pytest.raises(ValueError, match="name"):
        PerformanceRecorder(enabled=True).record("", 1)


@pytest.mark.parametrize("duration", [nan, inf, "12"])
def test_recorder_rejects_invalid_duration(duration):
    with pytest.raises(ValueError, match="elapsed_ms"):
        PerformanceRecorder(enabled=True).record("directory.list", duration)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [("session_token", 4), ("generation", True), ("path", 4)],
)
def test_recorder_rejects_invalid_correlation_context(field, value):
    with pytest.raises(TypeError):
        PerformanceRecorder(enabled=True).record("directory.list", 1, **{field: value})  # type: ignore[arg-type]


def test_measure_does_not_mask_body_exception_with_invalid_telemetry():
    recorder = PerformanceRecorder(enabled=True)

    with pytest.raises(RuntimeError, match="work failed"):
        with recorder.measure("", generation=True):
            raise RuntimeError("work failed")

    assert recorder.recent() == ()


def test_concurrent_recording_keeps_a_consistent_bounded_snapshot():
    recorder = PerformanceRecorder(enabled=True, max_events=100)

    def record_batch(worker: int) -> None:
        for item in range(40):
            recorder.record("worker", item, attributes={"worker": worker})

    workers = [threading.Thread(target=record_batch, args=(worker,)) for worker in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    events = recorder.recent()
    assert len(events) == 100
    assert all(event.name == "worker" for event in events)
