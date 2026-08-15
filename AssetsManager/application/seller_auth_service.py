"""Isolated seller authentication sessions for commerce administration."""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from typing import Any, Callable

from AssetsManager.application.app_settings_provider import get_app_settings
from AssetsManager.application.auth_service import AuthService
from AssetsManager.domain.errors import OperationNotPermitted, ValidationError

SELLER_SESSION_TTL = 12 * 60 * 60


def hash_seller_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _default_seller_feature_generation() -> int:
    try:
        return get_app_settings().get_seller_feature_generation()
    except Exception:
        # A missing settings provider must not prevent the auth service from
        # starting; the generation remains stable at the safe default.
        return 0


class SellerAuthService:
    """Authenticate seller access through isolated in-memory sessions.

    Seller credentials are verified by the existing ``AuthService`` and only
    active administrators may become sellers. The resulting random bearer is
    stored only as a SHA-256 hash and is accepted exclusively from the
    ``seller_session`` cookie by Commerce routes. It is never a ``lan_token``
    and cannot be interpreted as a normal LAN user token.
    """

    def __init__(self, auth_service: AuthService, *, clock=time.time,
                 session_ttl: int = SELLER_SESSION_TTL,
                 feature_generation: Callable[[], int] | None = None) -> None:
        self._auth_service = auth_service
        self._clock = clock
        self._session_ttl = int(session_ttl)
        self._feature_generation = feature_generation or _default_seller_feature_generation
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def _prune_locked(self, now: float) -> None:
        expired = [key for key, value in self._sessions.items()
                   if float(value["expires_at"]) <= now]
        for key in expired:
            self._sessions.pop(key, None)

    def login(self, username: str, password: str) -> tuple[dict[str, Any], str]:
        user = str(username).strip()
        if not user or not isinstance(password, str) or not password:
            raise ValidationError("credentials", "username and password are required")
        record, _error = self._auth_service.authenticate_user(user, password)
        if record is None or str(record.get("role", "")) != "admin":
            raise OperationNotPermitted("Invalid seller credentials")
        token = secrets.token_urlsafe(32)
        now = float(self._clock())
        seller = {
            "id": int(record["id"]),
            "username": str(record["username"]),
            "role": "seller",
            "expires_at": now + self._session_ttl,
            "_feature_generation": self._feature_generation_value(),
        }
        with self._lock:
            self._prune_locked(now)
            self._sessions[hash_seller_token(token)] = seller
        return self._public_seller(seller), token

    @staticmethod
    def _public_seller(seller: dict[str, Any]) -> dict[str, Any]:
        result = dict(seller)
        result.pop("_feature_generation", None)
        return result

    def _feature_generation_value(self) -> int:
        try:
            value = int(self._feature_generation())
        except Exception:
            return 0
        return max(0, value)

    def is_enabled(self) -> bool:
        """Seller login is available when the existing auth service is configured."""
        try:
            return bool(self._auth_service.has_active_users())
        except Exception:
            return True

    def _current_admin_is_valid(self, seller: dict[str, Any]) -> bool:
        """Fail closed when the persisted administrator loses seller authority."""
        try:
            session_generation = int(seller.get("_feature_generation", -1))
        except (TypeError, ValueError):
            return False
        if session_generation != self._feature_generation_value():
            return False
        try:
            current = self._auth_service.get_user_by_id(int(seller["id"]))
        except Exception:
            return False
        return bool(
            current
            and current.get("is_active")
            and str(current.get("role", "")) == "admin"
        )

    def authenticate(self, token: str) -> dict[str, Any] | None:
        if not isinstance(token, str) or len(token) < 20:
            return None
        now = float(self._clock())
        session_key = hash_seller_token(token)
        with self._lock:
            self._prune_locked(now)
            seller = self._sessions.get(session_key)
            if seller is None:
                return None
            if not self._current_admin_is_valid(seller):
                # Re-activation must require a fresh seller login; never revive
                # a session that was observed after losing administrator access.
                self._sessions.pop(session_key, None)
                return None
            return dict(seller)

    def revoke_all(self) -> int:
        """Revoke every in-memory Seller session during server teardown."""
        with self._lock:
            revoked = len(self._sessions)
            self._sessions.clear()
            return revoked

    def logout(self, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            return self._sessions.pop(hash_seller_token(token), None) is not None


