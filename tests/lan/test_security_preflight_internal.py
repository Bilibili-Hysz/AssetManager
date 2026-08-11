from unittest.mock import Mock


def test_constructed_private_server_requires_preflight_before_lifecycle(monkeypatch):
    from AssetsManager.lan.server import _LanServerImpl

    server = object.__new__(_LanServerImpl)
    server._requires_preflight = True
    server.auth_status = lambda: (False, "none")
    server._build_app = Mock()

    result = server.start(port=8765, bind="0.0.0.0")

    assert result["share_state"] == "confirmation_required"
    assert server._build_app.call_count == 0


def test_guarded_tunnel_property_cannot_start_without_authentication():
    from AssetsManager.lan.server import _LanServerImpl

    server = object.__new__(_LanServerImpl)
    server._tunnel = Mock()
    server._tunnel_start_block_reason = None
    server.auth_status = lambda: (False, "none")

    guarded = server.tunnel

    assert guarded.start(timeout=3) is None
    assert server._tunnel.start.call_count == 0
    assert server.tunnel_start_block_reason == "authentication_required"


def test_guarded_tunnel_property_delegates_authenticated_start():
    from AssetsManager.lan.server import _LanServerImpl

    server = object.__new__(_LanServerImpl)
    server._tunnel = Mock()
    server._tunnel_start_block_reason = "authentication_required"
    server._port = 8765
    server.auth_status = lambda: (True, "password")
    server._tunnel.start.return_value = "https://public.example"

    assert server.tunnel.start(timeout=4) == "https://public.example"
    server._tunnel.start.assert_called_once_with(timeout=4)
    assert server.tunnel_start_block_reason is None


def _facade_with_snapshot(impl):
    from AssetsManager.application.security_preflight import SecuritySnapshot
    from AssetsManager.lan import LanServer

    facade = LanServer.__new__(LanServer)
    facade._impl = impl
    facade._last_security_snapshot = SecuritySnapshot(
        share_state="local_active",
        tunnel_state="stopped",
        effective_auth={"enabled": True, "mode": "password"},
        confirmation_required=False,
        trusted_network_confirmed=False,
    )
    return facade


def test_lan_server_facade_mirrors_blocked_tunnel_into_security_snapshot():
    impl = Mock()
    impl.start_tunnel.return_value = None
    impl.tunnel_start_block_reason = "authentication_required"
    impl.auth_status.return_value = (False, "none")
    facade = _facade_with_snapshot(impl)

    assert facade.start_tunnel(timeout=2) is None
    assert facade.security_snapshot.tunnel_state == "blocked"
    assert facade.security_snapshot.failure_reason == "authentication_required"


def test_lan_server_facade_mirrors_tunnel_success_and_stop():
    impl = Mock()
    impl.start_tunnel.return_value = "https://public.example"
    facade = _facade_with_snapshot(impl)

    assert facade.start_tunnel(timeout=2) == "https://public.example"
    assert facade.security_snapshot.tunnel_state == "public_active"
    facade.stop_tunnel()
    assert facade.security_snapshot.tunnel_state == "stopped"
    assert facade.security_snapshot.failure_reason is None
