"""Deterministic DNS single-flight result sharing observation; no network."""
import json
import threading
from unittest.mock import patch
from AssetsManager.lan import utils

release = threading.Event()
entered = threading.Event()
calls = []

def resolver(name):
    calls.append(name)
    if name == "Ethernet":
        return "192.168.50.10"
    entered.set()
    if not release.wait(3):
        raise RuntimeError("test barrier timed out")
    return "10.8.0.2"

with patch.object(utils.socket, "if_nameindex", return_value=[(1, "Ethernet"), (2, "VPN")]), \
     patch.object(utils.socket, "gethostbyname", side_effect=resolver):
    first = utils._enumerate_private_ips(timeout=0.05)
    assert entered.is_set(), "worker did not reach DNS barrier"
    original_worker = utils._enum_worker
    timer = threading.Timer(0.15, release.set)
    timer.start()
    try:
        second = utils._enumerate_private_ips(timeout=2)
        print(json.dumps({
            "first_result": first,
            "follower_result": second,
            "same_worker": original_worker is utils._enum_worker,
            "worker_finished": not original_worker.is_alive(),
            "resolver_calls": calls,
        }, indent=2))
        assert first and not second, "reported lost-result defect did not reproduce"
        assert original_worker is utils._enum_worker
        assert not original_worker.is_alive()
    finally:
        release.set()
        timer.join()
        original_worker.join(3)
