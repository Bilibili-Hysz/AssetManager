import json

import pytest

from AssetsManager.application.security_preflight import (
    CURRENT_SHARE_SAFETY_ACK_VERSION,
    SecurityPreflight,
    bind_scope_expanded,
    confirmation_failure_reason,
    effective_auth,
    persist_successful_share_security_history,
    preflight_snapshot,
    security_preflight_from_settings,
    settings_security_history,
    settings_security_values,
)
from AssetsManager.core.settings import (
    SHARE_SAFETY_ACK_VERSION_KEY,
    TRUSTED_NETWORK_CONFIRMED_KEY,
    AppSettings,
)


def test_missing_security_fields_are_safe_defaults_and_require_confirmation():
    assert settings_security_values({}) == (0, False)

    snapshot = preflight_snapshot(sharing=True, bind="localhost")
    assert snapshot.share_state == "confirmation_required"
    assert snapshot.confirmation_required is True
    assert snapshot.failure_reason == "share_safety_ack_required"


def test_ack_version_must_match_current_contract_exactly():
    assert confirmation_failure_reason(ack_version=0) == "share_safety_ack_required"
    assert confirmation_failure_reason(ack_version=CURRENT_SHARE_SAFETY_ACK_VERSION - 1) == (
        "share_safety_ack_required"
    )
    assert confirmation_failure_reason(
        ack_version=CURRENT_SHARE_SAFETY_ACK_VERSION + 1,
        trusted_network_confirmed=True,
        bind="0.0.0.0",
        auth_status=(True, "password"),
    ) == "share_safety_ack_required"
    assert confirmation_failure_reason(
        ack_version=CURRENT_SHARE_SAFETY_ACK_VERSION,
        trusted_network_confirmed=True,
        bind="0.0.0.0",
        auth_status=(True, "password"),
    ) is None


def test_confirmations_are_distinct():
    preflight = SecurityPreflight()

    preflight.confirm_authenticated_lan()
    assert preflight.ack_version == 1
    assert preflight.trusted_network_confirmed is False

    preflight.confirm_trusted_lan()
    assert preflight.ack_version == 1
    assert preflight.trusted_network_confirmed is True


def test_authenticated_lan_does_not_replace_trusted_confirmation():
    assert confirmation_failure_reason(
        ack_version=1,
        trusted_network_confirmed=False,
        bind="192.168.1.10",
        auth_status=(True, "password"),
    ) is None
    assert confirmation_failure_reason(
        ack_version=1,
        trusted_network_confirmed=False,
        bind="192.168.1.10",
        auth_status=(False, "none"),
    ) == "trusted_network_confirmation_required"


def test_settings_history_is_carried_into_canonical_preflight():
    settings = {
        "lan_share_safety_ack_version": CURRENT_SHARE_SAFETY_ACK_VERSION,
        "lan_trusted_network_confirmed": True,
        "lan_share_last_successful_bind": "127.0.0.1",
        "lan_share_last_successful_auth": {"enabled": True, "mode": "password"},
    }

    assert settings_security_history(settings) == (
        "127.0.0.1",
        {"enabled": True, "mode": "password"},
    )
    preflight = security_preflight_from_settings(settings)
    snapshot = preflight.snapshot(
        sharing=True,
        bind="0.0.0.0",
        auth_status=(True, "password"),
    )
    assert snapshot.failure_reason == "bind_scope_expanded"


def test_malformed_persisted_history_is_ignored_without_inventing_posture():
    settings = {
        "lan_share_last_successful_bind": 123,
        "lan_share_last_successful_auth": {"enabled": "yes", "mode": "password"},
    }
    assert settings_security_history(settings) == (None, None)
    preflight = security_preflight_from_settings(settings)
    assert preflight.previous_bind is None
    assert preflight.previous_auth_status is None


def test_successful_security_history_persistence_is_observable():
    class _Settings:
        def __init__(self, result):
            self.result = result
            self.saved = 0
            self.history = None

        def set_share_security_history(self, bind, auth_status):
            self.history = (bind, auth_status)

        def save(self):
            self.saved += 1
            return self.result

    settings = _Settings(True)
    preflight = SecurityPreflight(settings=settings)
    assert persist_successful_share_security_history(
        preflight, bind="0.0.0.0", auth_status=(True, "key")
    ) is True
    assert settings.saved == 1
    assert settings.history == (
        "0.0.0.0",
        {"enabled": True, "mode": "key"},
    )

    failed_settings = _Settings(False)
    failed_preflight = SecurityPreflight(settings=failed_settings)
    assert persist_successful_share_security_history(
        failed_preflight, bind="localhost", auth_status=(False, "none")
    ) is False


def test_preflight_holder_normalizes_explicit_previous_auth_status():
    preflight = SecurityPreflight(
        ack_version=CURRENT_SHARE_SAFETY_ACK_VERSION,
        previous_bind="192.168.1.10",
        previous_auth_status=(True, "password"),
    )

    snapshot = preflight.snapshot(
        sharing=True,
        bind="192.168.1.10",
        auth_status=(False, "none"),
    )
    assert snapshot.failure_reason == "authentication_removed"


def test_bind_expansion_requires_reconfirmation():
    assert bind_scope_expanded("localhost", "0.0.0.0") is True
    assert confirmation_failure_reason(
        ack_version=1,
        trusted_network_confirmed=True,
        previous_bind="127.0.0.1",
        bind="192.168.1.10",
    ) == "bind_scope_expanded"


def test_authentication_removal_requires_reconfirmation_on_lan():
    assert confirmation_failure_reason(
        ack_version=1,
        trusted_network_confirmed=False,
        bind="0.0.0.0",
        auth_status=(False, "none"),
        previous_auth_status=(True, "key"),
    ) == "authentication_removed"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ((True, "password"), {"enabled": True, "mode": "password"}),
        ((True, "key"), {"enabled": True, "mode": "key"}),
        ((True, "user"), {"enabled": True, "mode": "user"}),
        (None, {"enabled": False, "mode": "none"}),
    ],
)
def test_effective_auth_uses_real_auth_status(status, expected):
    assert effective_auth(status) == expected


def test_trusted_lan_cannot_start_tunnel_without_authentication():
    snapshot = preflight_snapshot(
        sharing=True,
        bind="0.0.0.0",
        ack_version=1,
        trusted_network_confirmed=True,
        auth_status=(False, "none"),
        tunnel_requested=True,
    )
    assert snapshot.share_state == "local_active"
    assert snapshot.tunnel_state == "blocked"
    assert snapshot.failure_reason == "tunnel_authentication_required"


def test_unconfirmed_share_forces_requested_tunnel_stopped():
    snapshot = preflight_snapshot(
        sharing=True,
        bind="localhost",
        tunnel_requested=True,
        tunnel_starting=True,
    )

    assert snapshot.share_state == "confirmation_required"
    assert snapshot.tunnel_state == "stopped"
    assert snapshot.failure_reason == "share_safety_ack_required"


def test_off_share_forces_requested_tunnel_stopped():
    snapshot = preflight_snapshot(
        sharing=False,
        tunnel_requested=True,
        tunnel_starting=True,
    )

    assert snapshot.share_state == "off"
    assert snapshot.tunnel_state == "stopped"


def test_cancel_forces_tunnel_stopped_without_revoking_confirmation():
    preflight = SecurityPreflight(ack_version=CURRENT_SHARE_SAFETY_ACK_VERSION, trusted_network_confirmed=True)
    preflight.cancel()

    assert preflight.ack_version == CURRENT_SHARE_SAFETY_ACK_VERSION
    assert preflight.trusted_network_confirmed is True
    snapshot = preflight.snapshot(
        sharing=True,
        tunnel_requested=True,
        tunnel_starting=True,
    )

    assert snapshot.share_state == "off"
    assert snapshot.tunnel_state == "stopped"


def test_active_share_can_start_and_activate_tunnel():
    starting = preflight_snapshot(
        sharing=True,
        bind="localhost",
        ack_version=1,
        auth_status=(True, "password"),
        tunnel_starting=True,
    )
    active = preflight_snapshot(
        sharing=True,
        bind="localhost",
        ack_version=1,
        auth_status=(True, "password"),
        tunnel_requested=True,
    )

    assert starting.share_state == "local_active"
    assert starting.tunnel_state == "starting"
    assert active.share_state == "local_active"
    assert active.tunnel_state == "public_active"


def test_snapshot_is_stable_and_json_serializable():
    snapshot = preflight_snapshot(
        sharing=True,
        bind="localhost",
        ack_version=1,
        auth_status=(True, "password"),
    )
    payload = snapshot.to_dict()
    assert list(payload) == [
        "share_state",
        "tunnel_state",
        "effective_auth",
        "confirmation_required",
        "trusted_network_confirmed",
        "failure_reason",
    ]
    json.dumps(payload, sort_keys=True)


def test_security_fields_are_validated_without_changing_other_settings_behavior():
    settings = AppSettings()
    settings.set(SHARE_SAFETY_ACK_VERSION_KEY, 1)
    settings.set(TRUSTED_NETWORK_CONFIRMED_KEY, True)
    assert settings.get_share_safety_ack_version() == 1
    assert settings.get_trusted_network_confirmed() is True

    with pytest.raises(ValueError):
        settings.set(SHARE_SAFETY_ACK_VERSION_KEY, -1)
    with pytest.raises(ValueError):
        settings.set(TRUSTED_NETWORK_CONFIRMED_KEY, 1)
