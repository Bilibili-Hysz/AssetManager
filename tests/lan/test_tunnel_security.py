def _server_for_tunnel_gate(*, auth_enabled: bool):
    from AssetsManager.lan.server import _LanServerImpl

    calls = []

    class Tunnel:
        def __init__(self):
            self._port = None

        def start(self, *, timeout):
            calls.append(timeout)
            return "https://example.trycloudflare.com"

    server = _LanServerImpl.__new__(_LanServerImpl)
    server._port = 8765
    server._tunnel = Tunnel()
    server._tunnel_start_block_reason = None
    server.auth_status = lambda: (auth_enabled, "password" if auth_enabled else "none")
    return server, calls


def test_start_tunnel_rejects_unauthenticated_server_without_touching_tunnel():
    server, calls = _server_for_tunnel_gate(auth_enabled=False)

    assert server.start_tunnel(timeout=3) is None
    assert calls == []
    assert server.tunnel_start_block_reason == "authentication_required"


def test_start_tunnel_allows_configured_authentication_and_clears_old_block():
    server, calls = _server_for_tunnel_gate(auth_enabled=True)
    server._tunnel_start_block_reason = "authentication_required"

    assert server.start_tunnel(timeout=7) == "https://example.trycloudflare.com"
    assert calls == [7]
    assert server._tunnel._port == 8765
    assert server.tunnel_start_block_reason is None


def test_share_manager_rejects_unauthenticated_legacy_tunnel_path():
    from AssetsManager.lan.manager import ShareManager

    manager = ShareManager()
    manager._state["running"] = True
    manager._server = type("Server", (), {"auth_status": lambda _self: (False, "none")})()

    assert manager.start_tunnel(timeout=3) is None
    assert manager._tunnel is None
