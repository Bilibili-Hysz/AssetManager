"""Tests for domain/auth.py — pure crypto functions."""
import hashlib
import time

from AssetsManager.domain.auth import (
    generate_access_key,
    generate_share_token,
    generate_token,
    generate_user_token,
    hash_key,
    hash_password,
    is_password_hash,
    validate_password_strength,
    verify_auth_token,
    verify_key,
    verify_password,
    verify_share_token,
    verify_token,
    verify_user_token,
)


class TestPasswordHashing:

    def test_hash_password_returns_salt_key_format(self):
        h = hash_password("test123")
        parts = h.split(":")
        assert len(parts) == 2
        assert len(parts[0]) == 64  # 32-byte salt = 64 hex chars
        assert len(parts[1]) == 64  # 32-byte key = 64 hex chars

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
        assert len(parts) == 2
        assert parts[0].isdigit()  # timestamp

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
        # Token format: ts.user_id.sig
        parts = token.split(".")
        assert len(parts) == 3
        assert parts[1] == "42"

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
