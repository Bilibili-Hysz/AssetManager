"""Cross-process proof for POSIX stale library-lock recovery."""
import multiprocessing
import os

import pytest

from AssetsManager.core import library_lock
from AssetsManager.core.library_lock import LibraryAlreadyOpenError, LibraryLock


def _has_usable_posix_flock() -> bool:
    if os.name == "nt":
        return False
    try:
        import fcntl
    except ImportError:
        return False
    return callable(getattr(fcntl, "flock", None))


pytestmark = [
    pytest.mark.skipif(
        os.name == "nt", reason="Windows does not provide POSIX flock recovery"
    ),
    pytest.mark.skipif(
        not _has_usable_posix_flock(),
        reason="POSIX recovery requires a usable fcntl.flock",
    ),
]


def _lock_child(lock_path, start_barrier, release_barrier, results) -> None:
    lock = None
    try:
        start_barrier.wait(timeout=30)
        try:
            lock = LibraryLock(lock_path)
        except LibraryAlreadyOpenError:
            results.put("blocked")
        else:
            results.put("acquired")
        release_barrier.wait(timeout=30)
    except BaseException as error:  # pragma: no cover - child failure reporting
        results.put(f"error:{type(error).__name__}:{error}")
        try:
            release_barrier.wait(timeout=30)
        except BaseException:
            pass
    finally:
        if lock is not None:
            lock.release()


def _write_fake_lock_file(lock_file, pid: int) -> None:
    lock_file.write_text(
        f"{pid}\npython\nHOST\n00000000-0000-0000-0000-000000000000\n\n",
        encoding="utf-8",
    )


def test_recovery_guard_cleans_sidecar_on_normal_exit(tmp_path):
    """The recovery sidecar is transient after a successful guard window."""
    lock_file = tmp_path / "stale.lock"
    with library_lock._posix_stale_recovery_guard(lock_file):
        assert lock_file.with_name("stale.lock.recovery").is_file()
    assert not lock_file.with_name("stale.lock.recovery").exists()


def test_recovery_guard_cleans_sidecar_on_exception(tmp_path):
    """Exceptional recovery exits do not leave an accumulating sidecar."""
    lock_file = tmp_path / "stale.lock"
    with pytest.raises(RuntimeError, match="stop recovery"):
        with library_lock._posix_stale_recovery_guard(lock_file):
            assert lock_file.with_name("stale.lock.recovery").is_file()
            raise RuntimeError("stop recovery")
    assert not lock_file.with_name("stale.lock.recovery").exists()


def test_two_posix_processes_have_one_stale_lock_recovery_winner(tmp_path):
    """A stale marker cannot produce two independent POSIX lock owners."""
    lock_file = tmp_path / "stale.lock"
    _write_fake_lock_file(lock_file, 99999999)

    context = multiprocessing.get_context("spawn")
    start_barrier = context.Barrier(2)
    release_barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_lock_child,
            args=(str(lock_file), start_barrier, release_barrier, results),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()

    outcomes = [results.get(timeout=60) for _ in processes]
    for process in processes:
        process.join(timeout=60)
    assert all(process.exitcode == 0 for process in processes)
    assert sorted(outcomes) == ["acquired", "blocked"]
    assert not lock_file.with_name("stale.lock.recovery").exists()
