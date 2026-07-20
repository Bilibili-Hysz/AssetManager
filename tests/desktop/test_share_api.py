import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from AssetsManager.dialogs._share_api import ShareApiTask


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
