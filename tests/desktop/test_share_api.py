from unittest.mock import Mock


from AssetsManager.dialogs._share_api import ShareApiTask, ShareCreationTask
from AssetsManager.domain.errors import ValidationError


def test_share_api_task_emits_json_for_success(monkeypatch):
    response = Mock(status_code=201, content=b"{}")
    response.json.return_value = {"url": "http://localhost/share"}
    request = Mock(return_value=response)
    monkeypatch.setattr("requests.request", request)
    task = ShareApiTask(
        "POST", "http://localhost/api/shares", {"X-Test": "1"},
        {"paths": ["asset"]}, success_statuses=(200, 201),
    )
    results = []
    task.signals.finished.connect(lambda success, payload: results.append((success, payload)))

    task.run()

    assert results == [(True, {"url": "http://localhost/share"})]
    request.assert_called_once_with(
        "POST", "http://localhost/api/shares", headers={"X-Test": "1"},
        json={"paths": ["asset"]}, timeout=10,
    )


def test_share_api_task_hides_transport_failures(monkeypatch):
    monkeypatch.setattr("requests.request", Mock(side_effect=OSError("network unavailable")))
    task = ShareApiTask("GET", "http://localhost/api/shares")
    results = []
    task.signals.finished.connect(lambda success, payload: results.append((success, payload)))

    task.run()

    assert results == [(False, None)]


def test_share_creation_task_calls_service_and_builds_http_payload():
    share = Mock(id="share-1")
    share.to_public_dict.return_value = {"id": "share-1", "paths": ["asset"]}
    service = Mock()
    service.create_share.return_value = share
    task = ShareCreationTask(
        service,
        ["asset"],
        {"password": "secret123", "allow_preview": True},
        "https://192.168.1.2:8080",
        True,
    )
    results = []
    task.signals.finished.connect(lambda success, payload: results.append((success, payload)))

    task.run()

    assert results == [(
        True,
        {"id": "share-1", "paths": ["asset"], "url": "https://192.168.1.2:8080/s/share-1", "requires_key": True},
    )]
    service.create_share.assert_called_once_with(
        paths=["asset"], password="secret123", allow_preview=True,
    )


def test_share_creation_task_returns_stable_validation_error():
    service = Mock()
    service.create_share.side_effect = ValidationError("password", "Password is invalid")
    task = ShareCreationTask(service, ["asset"], {}, "http://localhost:8080", False)
    results = []
    task.signals.finished.connect(lambda success, payload: results.append((success, payload)))

    task.run()

    assert results == [(False, {"error": "Password is invalid"})]


def test_share_creation_task_hides_unexpected_errors_and_logs(caplog):
    service = Mock()
    service.create_share.side_effect = RuntimeError("boom")
    task = ShareCreationTask(service, ["asset"], {}, "http://localhost:8080", False)
    results = []
    task.signals.finished.connect(lambda success, payload: results.append((success, payload)))

    task.run()

    assert results == [(False, None)]
    assert "Share creation failed" in caplog.text


def test_share_creation_task_returns_stable_failure_for_none():
    service = Mock()
    service.create_share.return_value = None
    task = ShareCreationTask(service, ["asset"], {}, "http://localhost:8080", False)
    results = []
    task.signals.finished.connect(lambda success, payload: results.append((success, payload)))

    task.run()

    assert results == [(False, {"error": "Failed to create share link"})]


def test_share_creation_task_captures_session_and_runtime_epoch():
    session = Mock(event_token="session-1", is_closed=False)
    runtime = Mock(epoch="runtime-1")
    service = Mock(_session=session, _runtime=runtime)

    task = ShareCreationTask(service, ["asset"], session=session, runtime=runtime, generation=7)

    assert task._session is session
    assert task._runtime is runtime
    assert task._runtime_epoch == "runtime-1"
    assert task._generation == 7
