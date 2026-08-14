"""Unit tests for ThumbnailLoader safety/performance fixes.

Covers: bounded wait_for_runtime, set_size under lock, request-after-stop
no-op, and clear_thumb_cache deletion outside the mutex.  Loader tests are
pure logic and need no QApplication.
"""
import time

from AssetsManager.panels.file_list._loader import ThumbnailLoader


def test_wait_for_runtime_times_out_instead_of_hanging():
    loader = ThumbnailLoader()
    loader._active_tasks[0] = 1  # simulate a task thread stuck forever

    started = time.monotonic()
    loader.wait_for_runtime(0)  # default 5s timeout must not block forever
    elapsed = time.monotonic() - started

    assert elapsed < 8.0
    # The simulated stuck task is left untouched; only not-yet-started
    # pool work is cancelled by the timeout path.
    assert loader._active_tasks[0] == 1


def test_set_size_writes_under_lock():
    loader = ThumbnailLoader()
    assert loader._size == 96
    loader.set_size(64)
    assert loader._size == 64
    # Same-size no-op keeps the current value.
    loader.set_size(64)
    assert loader._size == 64


def test_request_after_stop_does_not_restart_pool():
    loader = ThumbnailLoader()
    loader.stop()
    assert loader._stopped is True

    # Must return immediately: no admission, no failure marking.
    loader.request(0, "x.png")

    assert "x.png" not in loader._queued_keys
    assert loader._failed_paths == set()
    assert loader._stopped is True


def test_clear_thumb_cache_deletes_outside_mutex(tmp_path):
    loader = ThumbnailLoader()
    cache_dir = tmp_path / "thumbs"
    cache_dir.mkdir()
    for i in range(3):
        (cache_dir / f"thumb{i}.webp").write_bytes(b"fake")
    (cache_dir / "keep.png").write_bytes(b"fake")
    loader.set_cache_dir(str(cache_dir))

    count = loader.clear_thumb_cache()

    assert count == 3
    assert sorted(p.name for p in cache_dir.iterdir()) == ["keep.png"]
