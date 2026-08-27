"""Windows-safe import recovery after abrupt child-process termination."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_WAIT_TIMEOUT = 15.0
_POLL_INTERVAL = 0.01
_REPO_ROOT = Path(__file__).resolve().parents[2]

_CHILD_SCRIPT = textwrap.dedent(
    r'''
    from __future__ import annotations

    import json
    from pathlib import Path
    import sys
    import time

    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.application.import_manifest_store import ImportManifestStore
    from AssetsManager.application.import_service import ImportService


    def write_json(path_text, payload):
        path = Path(path_text)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(path)


    def wait_checkpoint(status_path, control_path, payload):
        write_json(status_path, payload)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline and not Path(control_path).exists():
            time.sleep(0.01)
        if not Path(control_path).exists():
            raise TimeoutError("parent did not release import checkpoint")


    def main():
        root_text, source_text, destination_text, mode, status_text, control_text, marker_text = sys.argv[1:]
        root = Path(root_text)
        source = Path(source_text)
        destination = Path(destination_text)
        status_path = Path(status_text)
        control_path = Path(control_text)
        marker_path = Path(marker_text)
        bootstrap = None
        try:
            source.write_text("original", encoding="utf-8")
            bootstrap = ApplicationBootstrap()
            session = bootstrap.library_service.open_session(root)
            services = bootstrap.runtime_for(session).services
            store = services.file_operation_service._import_manifest_store
            real_create = ImportManifestStore.create
            real_copy_one = ImportService._copy_one
            real_update_item = store.update_item
            operation_holder = {}

            def checkpoint_create(instance, **kwargs):
                operation_holder["operation_id"] = kwargs["operation_id"]
                result = real_create(instance, **kwargs)
                if mode == "before_copy":
                    payload = kwargs["payload"]
                    wait_checkpoint(
                        status_path,
                        control_path,
                        {
                            "phase": "before_copy",
                            "operation_id": kwargs["operation_id"],
                            "target": payload["items"][0]["target"],
                        },
                    )
                return result

            ImportManifestStore.create = checkpoint_create

            def checkpoint_copy(instance, src, rel, destination_dir, target=None, **kwargs):
                result = real_copy_one(instance, src, rel, destination_dir, target, **kwargs)
                marker_path.write_text(
                    marker_path.read_text(encoding="utf-8") + "copy\n"
                    if marker_path.exists()
                    else "copy\n",
                    encoding="utf-8",
                )
                if mode == "after_copy_before_item_update":
                    wait_checkpoint(
                        status_path,
                        control_path,
                        {
                            "phase": "after_copy_before_item_update",
                            "operation_id": operation_holder["operation_id"],
                            "target": str(result),
                        },
                    )
                return result

            def checkpoint_update(operation_id, **kwargs):
                result = real_update_item(operation_id, **kwargs)
                if mode == "after_item_update_before_finish" and result:
                    record = store.get(operation_id)
                    target = record["payload"]["items"][kwargs["item_index"]]["target"]
                    wait_checkpoint(
                        status_path,
                        control_path,
                        {
                            "phase": "after_item_update_before_finish",
                            "operation_id": operation_id,
                            "target": target,
                        },
                    )
                return result

            ImportService._copy_one = checkpoint_copy
            store.update_item = checkpoint_update
            service = ImportService(session, services.file_operation_service)
            result = service.import_sources([source], destination)
            write_json(
                status_path,
                {
                    "phase": "completed",
                    "operation_id": result.operation_id,
                    "copied": result.copied,
                },
            )
        except BaseException as error:
            write_json(
                status_path,
                {"phase": "error", "type": type(error).__name__, "message": str(error)},
            )
            raise
        finally:
            if bootstrap is not None:
                bootstrap.library_service.close()


    if __name__ == "__main__":
        main()
    ''',
)


def _start_child(*arguments: object) -> subprocess.Popen:
    environment = os.environ.copy()
    pythonpath = str(_REPO_ROOT)
    if environment.get("PYTHONPATH"):
        pythonpath += os.pathsep + environment["PYTHONPATH"]
    environment["PYTHONPATH"] = pythonpath
    return subprocess.Popen(
        [sys.executable, "-c", _CHILD_SCRIPT, *(str(value) for value in arguments)],
        cwd=str(_REPO_ROOT),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def _wait_json(path: Path, *, timeout: float = _WAIT_TIMEOUT) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if path.exists():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise AssertionError(f"status is not an object: {value!r}")
                if value.get("phase") == "error":
                    raise AssertionError(f"child failed: {value!r}")
                return value
            except (OSError, json.JSONDecodeError, AssertionError) as error:
                last_error = error
        time.sleep(_POLL_INTERVAL)
    raise AssertionError(f"timed out waiting for {path}; last_error={last_error!r}")


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3.0)


def _reopen_and_recover(root: Path):
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(root)
    services = bootstrap.runtime_for(session).services
    return bootstrap, session, services


@pytest.mark.parametrize(
    "mode, expected_item_state, expect_target",
    (
        ("before_copy", "pending", False),
        ("after_copy_before_item_update", "pending", True),
        ("after_item_update_before_finish", "copied", True),
    ),
)
def test_import_subprocess_termination_recovers_without_copy_replay(
    tmp_path, mode, expected_item_state, expect_target,
):
    root = tmp_path / "library"
    root.mkdir()
    source = tmp_path / "source.txt"
    destination = root / "dest"
    status = tmp_path / f"{mode}-status.json"
    control = tmp_path / f"{mode}-release"
    marker = tmp_path / f"{mode}-copies.log"
    child = None
    try:
        child = _start_child(root, source, destination, mode, status, control, marker)
        checkpoint = _wait_json(status)
        assert checkpoint["phase"] == mode
        operation_id = checkpoint["operation_id"]
        assert isinstance(operation_id, str) and operation_id.startswith("import-")
        target = Path(str(checkpoint["target"]))
        assert target == (destination / "source.txt").resolve()
        assert child.poll() is None
        _stop_process(child)
        child = None

        copies_before = marker.read_text(encoding="utf-8") if marker.exists() else ""
        assert copies_before.count("copy\n") == (1 if expect_target else 0)
        if expect_target:
            assert target.read_text(encoding="utf-8") == "original"
        else:
            assert not target.exists()

        restarted, session, services = _reopen_and_recover(root)
        try:
            store = services.file_operation_service._import_manifest_store
            record = store.get(operation_id)
            assert record is not None
            assert record["state"] == "completed"
            assert record["attempts"] == 1
            assert record["payload"]["items"][0]["state"] == expected_item_state
            tasks = services.reconciliation_queue.snapshot()
            recovery_tasks = [
                task for task in tasks
                if task.reason == "import_manifest_recovery"
                and operation_id in task.operation_ids
            ]
            assert len(recovery_tasks) == 1
            recovery_task_id = recovery_tasks[0].task_id
            if expect_target:
                assert target.read_text(encoding="utf-8") == "original"
        finally:
            restarted.library_service.close()

        second, second_session, second_services = _reopen_and_recover(root)
        try:
            second_tasks = second_services.reconciliation_queue.snapshot()
            matching = [task for task in second_tasks if operation_id in task.operation_ids]
            assert len(matching) == 1
            assert matching[0].task_id == recovery_task_id
            assert matching[0].operation_ids.count(operation_id) == 1
            copies_after = marker.read_text(encoding="utf-8") if marker.exists() else ""
            assert copies_after == copies_before
        finally:
            second.library_service.close()
    finally:
        control.touch()
        _stop_process(child)
