"""Tests for domain/auth.py — pure crypto functions."""
import hashlib
import hmac
import os
import time

import pytest

from AssetsManager.domain import auth as auth_module
from AssetsManager.domain.auth import (
    generate_access_key,
    generate_share_token,
    generate_token,
    generate_user_token,
    hash_key,
    hash_password,
    is_password_hash,
    needs_password_rehash,
    validate_password_strength,
    verify_auth_token,
    verify_key,
    verify_password,
    verify_share_token,
    verify_token,
    verify_user_token,
)


def _legacy_hash(password: str) -> str:
    """Build a hash in the pre-versioning bare ``salt:key`` format."""
    salt = b"\x11" * 32
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        auth_module.LEGACY_PASSWORD_ITERATIONS,
    )
    return f"{salt.hex()}:{key.hex()}"


class TestPasswordHashing:

    def test_hash_password_returns_versioned_format(self):
        h = hash_password("test123")
        parts = h.split("$")
        assert len(parts) == 4
        assert parts[0] == "pbkdf2_sha256"
        assert int(parts[1]) == auth_module.PASSWORD_ITERATIONS
        assert len(parts[2]) == 64  # 32-byte salt = 64 hex chars
        assert len(parts[3]) == 64  # 32-byte key = 64 hex chars

    def test_hash_password_different_each_time(self):
        h1 = hash_password("test")
        h2 = hash_password("test")
        assert h1 != h2  # Different salts

    def test_verify_password_correct(self):
        h = hash_password("mypassword")
        assert verify_password("mypassword", h) is True

    def test_verify_password_wrong(self):
        h = hash_password("mypassword")
        assert verify_password("wrong", h) is False

    def test_verify_password_malformed_hash(self):
        assert verify_password("test", "not_a_hash") is False
        assert verify_password("test", "") is False

    def test_verify_password_rejects_non_numeric_iterations(self):
        h = hash_password("mypassword")
        _, _, salt, key = h.split("$")
        assert verify_password("mypassword", f"pbkdf2_sha256$abc${salt}${key}") is False

    def test_verify_password_rejects_zero_iterations(self):
        h = hash_password("mypassword")
        _, _, salt, key = h.split("$")
        assert verify_password("mypassword", f"pbkdf2_sha256$0${salt}${key}") is False


class TestProductionCosts:
    """Guard the shipped PBKDF2 costs against accidental downgrades.

    These tests opt out of the suite-wide fast-PBKDF2 override via the
    ``real_pbkdf2_cost`` marker, so they assert the production values
    themselves.  Any deliberate cost change must therefore be edited here
    explicitly instead of silently passing the rest of the suite.
    """

    @pytest.mark.real_pbkdf2_cost
    def test_password_iterations(self):
        assert auth_module.PASSWORD_ITERATIONS == 600_000

    @pytest.mark.real_pbkdf2_cost
    def test_legacy_iterations(self):
        assert auth_module.LEGACY_PASSWORD_ITERATIONS == 100_000

    @pytest.mark.real_pbkdf2_cost
    def test_key_iterations(self):
        assert auth_module.KEY_ITERATIONS == 50_000

    @pytest.mark.real_pbkdf2_cost
    def test_production_legacy_hash_still_verifies(self):
        # The bare legacy format carries no cost field, so it must keep
        # verifying while the module constant holds the production value.
        salt = b"\x77" * 32
        key = hashlib.pbkdf2_hmac(
            "sha256", b"legacy-pw", salt, auth_module.LEGACY_PASSWORD_ITERATIONS
        )
        stored = f"{salt.hex()}:{key.hex()}"
        assert verify_password("legacy-pw", stored) is True


class TestCrossCostVerification:
    """Hashes minted at any cost must verify regardless of the current one."""

    def test_production_cost_hash_verifies_under_test_cost(self):
        # The versioned format embeds its cost, so verification replays the
        # stored cost even though the fixture downgraded the module constant.
        cheap = hash_password("cross")
        salt = os.urandom(32)
        key = hashlib.pbkdf2_hmac("sha256", b"cross", salt, 600_000)
        prod = f"pbkdf2_sha256$600000${salt.hex()}${key.hex()}"
        assert verify_password("cross", cheap) is True
        assert verify_password("cross", prod) is True
        assert verify_password("wrong", prod) is False


class TestLegacyPasswordHashes:
    """Hashes written before the versioned format must keep working."""

    def test_legacy_hash_still_verifies(self):
        h = _legacy_hash("mypassword")
        assert verify_password("mypassword", h) is True

    def test_legacy_hash_rejects_wrong_password(self):
        h = _legacy_hash("mypassword")
        assert verify_password("wrong", h) is False

    def test_legacy_hash_is_recognized_as_password_hash(self):
        assert is_password_hash(_legacy_hash("mypassword")) is True


class TestNeedsPasswordRehash:

    def test_current_hash_needs_no_rehash(self):
        assert needs_password_rehash(hash_password("test")) is False

    def test_legacy_hash_needs_rehash(self):
        assert needs_password_rehash(_legacy_hash("test")) is True

    def test_lower_cost_versioned_hash_needs_rehash(self):
        h = hash_password("test")
        _, _, salt, key = h.split("$")
        low = f"pbkdf2_sha256${auth_module.PASSWORD_ITERATIONS - 1}${salt}${key}"
        assert needs_password_rehash(low) is True

    def test_unparseable_hash_needs_no_rehash(self):
        # It cannot be verified either, so there is nothing to migrate.
        assert needs_password_rehash("not_a_hash") is False
        assert needs_password_rehash("") is False


class TestKeyHashing:

    def test_hash_key_returns_salt_key_format(self):
        h = hash_key("mykey")
        parts = h.split(":")
        assert len(parts) == 2
        assert len(parts[0]) == 32  # 16-byte salt = 32 hex chars
        assert len(parts[1]) == 64  # 32-byte key = 64 hex chars

    def test_verify_key_correct(self):
        h = hash_key("mykey")
        assert verify_key("mykey", h) is True

    def test_verify_key_wrong(self):
        h = hash_key("mykey")
        assert verify_key("wrong", h) is False


class TestIsPasswordHash:

    def test_valid_password_hash(self):
        h = hash_password("test")
        assert is_password_hash(h) is True

    def test_plaintext_returns_false(self):
        assert is_password_hash("mypassword") is False
        assert is_password_hash("") is False

    def test_key_hash_returns_false(self):
        h = hash_key("test")
        assert is_password_hash(h) is False  # 16-byte salt = 32 hex, not 64


class TestTokenGeneration:

    def test_generate_token_format(self):
        h = hash_password("test")
        token = generate_token(h)
        parts = token.split(".")
        assert len(parts) == 3
        assert parts[0].isdigit()  # timestamp
        assert len(parts[1]) == 8  # nonce (4 random bytes, hex)

    def test_generate_token_unique_same_second(self):
        h = hash_password("test")
        tokens = {generate_token(h) for _ in range(50)}
        assert len(tokens) == 50  # nonce makes same-second tokens distinct

    def test_verify_token_legacy_format(self):
        h = hash_password("test")
        ts = str(int(time.time()))
        sig = hmac.new(h.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]
        legacy = f"{ts}.{sig}"
        assert verify_token(legacy, h) is True

    def test_verify_token_valid(self):
        h = hash_password("test")
        token = generate_token(h)
        assert verify_token(token, h) is True

    def test_verify_token_wrong_hash(self):
        h1 = hash_password("test")
        h2 = hash_password("other")
        token = generate_token(h1)
        assert verify_token(token, h2) is False

    def test_verify_token_expired(self):
        h = hash_password("test")
        ts = str(int(time.time()) - 90000)  # 25 hours ago
        import hashlib
        sig = hashlib.sha256(f"{ts}:{h}".encode()).hexdigest()[:32]
        token = f"{ts}.{sig}"
        assert verify_token(token, h) is False


class TestAuthToken:

    def test_verify_auth_token_valid(self):
        from AssetsManager.lan.utils import generate_auth_token
        secret = "test-secret"
        token = generate_auth_token(secret)
        assert verify_auth_token(token, secret) is True
        assert len(token.split(".")) == 3  # ts.nonce.sig

    def test_generate_auth_token_unique_same_second(self):
        from AssetsManager.lan.utils import generate_auth_token
        tokens = {generate_auth_token("test-secret") for _ in range(50)}
        assert len(tokens) == 50  # nonce makes same-second tokens distinct

    def test_verify_auth_token_legacy_format(self):
        secret = "test-secret"
        ts = str(int(time.time()))
        sig = hmac.new(secret.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]
        legacy = f"{ts}.{sig}"
        assert verify_auth_token(legacy, secret) is True

    def test_verify_auth_token_wrong_secret(self):
        from AssetsManager.lan.utils import generate_auth_token
        token = generate_auth_token("secret-a")
        assert verify_auth_token(token, "secret-b") is False

    def test_verify_auth_token_expired(self):
        import hashlib
        secret = "test-secret"
        ts = str(int(time.time()) - 90000)
        sig = hashlib.sha256(f"{ts}:{secret}".encode()).hexdigest()[:32]
        token = f"{ts}.{sig}"
        assert verify_auth_token(token, secret) is False


class TestUserToken:

    def test_generate_and_verify(self):
        secret = "test-secret"
        token = generate_user_token(42, "alice", "admin", secret)
        # Token format: ts.user_id.nonce.sig
        parts = token.split(".")
        assert len(parts) == 4
        assert parts[1] == "42"
        assert len(parts[2]) == 8  # nonce (4 random bytes, hex)

    def test_generate_user_token_unique_same_second(self):
        secret = "test-secret"
        tokens = {
            generate_user_token(42, "alice", "admin", secret) for _ in range(50)
        }
        assert len(tokens) == 50  # nonce makes same-second tokens distinct

    def test_verify_user_token_legacy_format(self):
        secret = "test-secret"
        ts = str(int(time.time()))
        payload = f"{ts}.42.alice.admin"
        sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
        legacy = f"{ts}.42.{sig}"
        user_info = {"id": 42, "username": "alice", "role": "admin", "is_active": True}
        assert verify_user_token(legacy, secret, user_info=user_info) is not None
        assert verify_user_token(
            legacy, secret, user_info=user_info,
        ) == {"id": 42, "username": "alice", "role": "admin"}

    def test_verify_user_token_needs_user_info(self):
        secret = "test-secret"
        token = generate_user_token(42, "alice", "admin", secret)
        # Without user_info, verification returns None
        assert verify_user_token(token, secret, user_info=None) is None

    def test_verify_user_token_with_valid_user_info(self):
        secret = "test-secret"
        token = generate_user_token(42, "alice", "admin", secret)
        user_info = {"id": 42, "username": "alice", "role": "admin", "is_active": True}
        result = verify_user_token(token, secret, user_info=user_info)
        assert result is not None
        assert result["id"] == 42
        assert result["username"] == "alice"
        assert result["role"] == "admin"

    def test_verify_user_token_rejects_inactive_user(self):
        secret = "test-secret"
        token = generate_user_token(42, "alice", "admin", secret)
        user_info = {"id": 42, "username": "alice", "role": "admin", "is_active": False}
        assert verify_user_token(token, secret, user_info=user_info) is None

    def test_verify_user_token_rejects_mismatched_user_id(self):
        secret = "test-secret"
        token = generate_user_token(42, "alice", "admin", secret)
        user_info = {"id": 99, "username": "alice", "role": "admin", "is_active": True}
        assert verify_user_token(token, secret, user_info=user_info) is None


class TestShareToken:

    def test_generate_and_verify(self):
        secret = "test-secret"
        token = generate_share_token("share123", secret)
        assert verify_share_token(token, "share123", secret) is True
        assert len(token.split(".")) == 3  # ts.nonce.sig

    def test_generate_share_token_unique_same_second(self):
        secret = "test-secret"
        tokens = {generate_share_token("share123", secret) for _ in range(50)}
        assert len(tokens) == 50  # nonce makes same-second tokens distinct

    def test_verify_share_token_legacy_format(self):
        secret = "test-secret"
        ts = str(int(time.time()))
        message = f"{ts}.share123"
        sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()[:32]
        legacy = f"{ts}.{sig}"
        assert verify_share_token(legacy, "share123", secret) is True

    def test_verify_wrong_share_id(self):
        secret = "test-secret"
        token = generate_share_token("share123", secret)
        assert verify_share_token(token, "share456", secret) is False

    def test_verify_expired(self):
        import hashlib
        secret = "test-secret"
        ts = str(int(time.time()) - 7200)  # 2 hours ago (TTL is 1h)
        sig = hashlib.sha256(f"{ts}.share123:{secret}".encode()).hexdigest()[:32]
        token = f"{ts}.{sig}"
        assert verify_share_token(token, "share123", secret) is False


class TestPasswordStrength:

    def test_valid_password(self):
        assert validate_password_strength("MyP@ssw1") is None

    def test_too_short(self):
        assert validate_password_strength("Sh0!") is not None

    def test_no_uppercase(self):
        assert validate_password_strength("mypassword1!") is not None

    def test_no_digit(self):
        assert validate_password_strength("MyPassword!") is not None

    def test_no_special(self):
        assert validate_password_strength("MyPassword1") is not None

    def test_empty(self):
        assert validate_password_strength("") is not None

    def test_common_password(self):
        assert validate_password_strength("password") is not None


class TestAccessKey:

    def test_generate_access_key_length(self):
        key = generate_access_key()
        assert len(key) == 32  # 16 bytes = 32 hex chars

    def test_generate_access_key_unique(self):
        keys = {generate_access_key() for _ in range(100)}
        assert len(keys) == 100


class TestHMACMigration:
    """Regression: old SHA-256 tokens must be rejected after HMAC migration."""

    def test_old_sha256_token_rejected_by_verify_token(self):
        h = hash_password("test")
        ts = str(int(time.time()))
        old_sig = hashlib.sha256(f"{ts}:{h}".encode()).hexdigest()[:32]
        old_token = f"{ts}.{old_sig}"
        assert verify_token(old_token, h) is False

    def test_old_sha256_token_rejected_by_verify_auth_token(self):
        secret = "test-secret"
        ts = str(int(time.time()))
        old_sig = hashlib.sha256(f"{ts}:{secret}".encode()).hexdigest()[:32]
        old_token = f"{ts}.{old_sig}"
        assert verify_auth_token(old_token, secret) is False

    def test_old_sha256_token_rejected_by_verify_user_token(self):
        secret = "test-secret"
        ts = str(int(time.time()))
        payload = f"{ts}.42.alice.admin"
        old_sig = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:32]
        old_token = f"{ts}.42.{old_sig}"
        user_info = {"id": 42, "username": "alice", "role": "admin", "is_active": True}
        assert verify_user_token(old_token, secret, user_info=user_info) is None

    def test_old_sha256_token_rejected_by_verify_share_token(self):
        secret = "test-secret"
        ts = str(int(time.time()))
        old_sig = hashlib.sha256(f"{ts}.share123:{secret}".encode()).hexdigest()[:32]
        old_token = f"{ts}.{old_sig}"
        assert verify_share_token(old_token, "share123", secret) is False
