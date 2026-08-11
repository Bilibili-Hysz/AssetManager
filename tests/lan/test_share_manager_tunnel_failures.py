from types import SimpleNamespace
from unittest.mock import Mock


def _tunnel_manager(monkeypatch, tunnel):
    from AssetsManager.lan.manager import ShareManager

    tunnel.is_running = False
    monkeypatch.setattr(
        "AssetsManager.lan.manager.TunnelManager",
        Mock(return_value=tunnel),
    )
    manager = ShareManager()
    manager._state["running"] = True
    manager._server = type(
        "Server",
        (),
        {"auth_status": lambda _self: (True, "password")},
    )()
    return manager


def test_start_tunnel_none_stops_candidate_and_notifies(monkeypatch):
    tunnel = Mock()
    tunnel.start.return_value = None
    manager = _tunnel_manager(monkeypatch, tunnel)
    callback = Mock()
    manager.on_state_change(callback)

    assert manager.start_tunnel(timeout=3) is None

    tunnel.start.assert_called_once_with(timeout=3)
    tunnel.stop.assert_called_once_with()
    assert manager._tunnel is None
    assert manager.status()["tunnel_state"] == "stopped"
    assert manager.status()["tunnel_running"] is False
    assert manager.status()["failure_reason"] == "tunnel_start_failed"
    assert callback.call_count >= 2


def test_start_tunnel_exception_stops_candidate_and_notifies(monkeypatch):
    tunnel = Mock()
    tunnel.start.side_effect = RuntimeError("boom")
    manager = _tunnel_manager(monkeypatch, tunnel)
    callback = Mock()
    manager.on_state_change(callback)

    assert manager.start_tunnel() is None

    tunnel.stop.assert_called_once_with()
    assert manager.status()["tunnel_state"] == "stopped"
    assert manager.status()["failure_reason"] == "tunnel_start_failed"
    assert callback.call_count >= 2


def test_failed_start_can_be_retried(monkeypatch):
    failed = Mock()
    failed.is_running = False
    failed.start.return_value = None
    started = Mock()
    started.is_running = True
    started.start.return_value = "https://public.example"
    tunnel_factory = Mock(side_effect=[failed, started])
    monkeypatch.setattr("AssetsManager.lan.manager.TunnelManager", tunnel_factory)

    from AssetsManager.lan.manager import ShareManager

    manager = ShareManager()
    manager._state["running"] = True
    manager._server = type(
        "Server",
        (),
        {"auth_status": lambda _self: (True, "password")},
    )()

    assert manager.start_tunnel() is None
    assert manager.status()["failure_reason"] == "tunnel_start_failed"
    assert manager.start_tunnel() == "https://public.example"
    assert manager.status()["tunnel_state"] == "public_active"
    assert manager.status()["failure_reason"] is None
    failed.stop.assert_called_once_with()
    started.stop.assert_not_called()


def test_failed_retry_does_not_replace_live_old_tunnel(monkeypatch):
    old = Mock()
    failed = Mock()
    failed.start.return_value = None
    manager = _tunnel_manager(monkeypatch, failed)
    manager._tunnel = old
    manager._state["tunnel_running"] = False

    assert manager.start_tunnel() is None

    assert manager._tunnel is old
    old.stop.assert_not_called()
    failed.stop.assert_called_once_with()


def test_missing_auth_status_remains_fail_closed(monkeypatch):
    tunnel = Mock()
    manager = _tunnel_manager(monkeypatch, tunnel)
    manager._server = object()

    assert manager.start_tunnel() is None

    tunnel.start.assert_not_called()
    tunnel.stop.assert_not_called()
    assert manager.status()["tunnel_state"] == "blocked"
    assert manager.status()["failure_reason"] == "authentication_status_unavailable"


def _snapshot(share_state, *, failure_reason=None):
    payload = {
        "share_state": share_state,
        "tunnel_state": "stopped",
        "confirmation_required": share_state == "confirmation_required",
        "trusted_network_confirmed": False,
        "failure_reason": failure_reason,
        "effective_auth": {"enabled": True, "mode": "password"},
    }
    return SimpleNamespace(
        share_state=share_state,
        effective_auth=payload["effective_auth"],
        to_dict=lambda: payload,
    )


def _patch_start_dependencies(monkeypatch, server, post_snapshot):
    import AssetsManager.lan as lan

    monkeypatch.setattr(lan, "is_available", lambda: True)
    monkeypatch.setattr(lan, "LanServer", lambda **_kwargs: server)
    monkeypatch.setattr(
        "AssetsManager.lan.server.get_local_ip",
        lambda: "127.0.0.1",
    )
    preflight = Mock()
    preflight.snapshot.side_effect = [_snapshot("local_active"), post_snapshot]
    return preflight


def test_start_result_confirmation_required_clears_rolled_back_server(monkeypatch):
    from AssetsManager.lan.manager import ShareManager

    server = Mock()
    server.start.return_value = {"share_state": "confirmation_required"}
    server.is_running.return_value = False
    preflight = _patch_start_dependencies(monkeypatch, server, _snapshot("confirmation_required"))
    manager = ShareManager()

    result = manager.start(runtime=object(), password="secret", preflight=preflight)

    assert result["share_state"] == "confirmation_required"
    assert result["running"] is False
    assert manager._server is None


def test_start_result_rollback_failed_retains_running_server(monkeypatch):
    from AssetsManager.lan.manager import ShareManager

    server = Mock()
    server.start.return_value = {
        "share_state": "failed",
        "failure_reason": "rollback_failed",
        "rollback_failed": True,
        "running": True,
    }
    server.is_running.return_value = True
    preflight = _patch_start_dependencies(monkeypatch, server, _snapshot("failed", failure_reason="rollback_failed"))
    manager = ShareManager()

    result = manager.start(runtime=object(), password="secret", preflight=preflight)

    assert result["share_state"] == "failed"
    assert result["running"] is True
    assert manager._server is server



def test_post_start_auth_recheck_stops_server_before_reporting_block(monkeypatch):
    from AssetsManager.lan.manager import ShareManager

    server = Mock()
    server.start.return_value = None
    server.is_running.return_value = True
    server.stop.side_effect = lambda: server.is_running.configure_mock(return_value=False)
    preflight = _patch_start_dependencies(monkeypatch, server, _snapshot("confirmation_required"))
    manager = ShareManager()

    result = manager.start(runtime=object(), password="secret", preflight=preflight)

    server.stop.assert_called_once_with()
    assert result["running"] is False
    assert manager._server is None


def test_post_start_auth_recheck_retains_server_when_rollback_fails(monkeypatch):
    from AssetsManager.lan.manager import ShareManager

    server = Mock()
    server.start.return_value = None
    server.is_running.return_value = True
    server.stop.side_effect = RuntimeError("stop failed")
    preflight = _patch_start_dependencies(monkeypatch, server, _snapshot("confirmation_required"))
    manager = ShareManager()

    result = manager.start(runtime=object(), password="secret", preflight=preflight)

    server.stop.assert_called_once_with()
    assert result["running"] is True
    assert result["share_state"] == "failed"
    assert result["failure_reason"] == "security_post_start_rollback_failed"
    assert manager._server is server


def test_failed_tunnel_cleanup_failure_retains_candidate_and_reports_failed(monkeypatch):
    tunnel = Mock()
    tunnel.is_running = True
    tunnel.start.return_value = None
    tunnel.stop.side_effect = RuntimeError("cleanup failed")
    manager = _tunnel_manager(monkeypatch, tunnel)
    tunnel.is_running = True

    assert manager.start_tunnel() is None

    assert manager._tunnel is tunnel
    assert manager.status()["tunnel_running"] is True
    assert manager.status()["tunnel_state"] == "failed"
    assert manager.status()["failure_reason"] == "tunnel_cleanup_failed"


def test_failed_tunnel_state_is_mirrored_into_security_snapshot(monkeypatch):
    tunnel = Mock()
    tunnel.is_running = False
    tunnel.start.return_value = None
    manager = _tunnel_manager(monkeypatch, tunnel)
    manager._state["security"] = {
        "share_state": "local_active",
        "tunnel_state": "stopped",
        "failure_reason": None,
    }

    assert manager.start_tunnel() is None

    assert manager.status()["security"]["tunnel_state"] == "stopped"
    assert manager.status()["security"]["failure_reason"] == "tunnel_start_failed"


def test_stop_tunnel_cleanup_failure_retains_handle(monkeypatch):
    tunnel = Mock()
    tunnel.is_running = True
    tunnel.stop.side_effect = RuntimeError("stop failed")
    manager = _tunnel_manager(monkeypatch, tunnel)
    manager._tunnel = tunnel
    manager._state["tunnel_running"] = True

    manager.stop_tunnel()

    assert manager._tunnel is tunnel
    assert manager.status()["tunnel_state"] == "failed"
    assert manager.status()["failure_reason"] == "tunnel_cleanup_failed"
