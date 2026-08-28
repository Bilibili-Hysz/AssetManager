"""Auth-token revocation registry for the LAN server.

Moved from ``lan/server.py``.  The registry is *host-bound*: it stores its
in-memory revocation table on the host server (``host._revoked_tokens`` /
``host._revoked_loaded``) so the existing skeleton-test pattern that assigns
those attributes directly keeps working unchanged.  The only behavior change is
where the methods live; the logic is identical.

Registry methods may run concurrently in worker threads; all cache and load
state is protected by the registry locks.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any, cast

_log = logging.getLogger(__name__)


class TokenRevocationPersistenceError(RuntimeError):
    """Raised when durable token revocation cannot be recorded."""


class TokenRevocationRegistry:
    """TTL-bounded positive cache of revoked auth tokens, persisted via AuthService.

    The in-memory table is the hot-path positive cache; the library DB (via the
    bound AuthService) is the durable source of truth across app restarts, so a
    token signed with the persisted password hash cannot resurrect after an
    app restart.
    """

    _TOKEN_REVOCATION_TTL = 86400.0
    _TOKEN_REVOCATION_MAX = 10_000

    def __init__(self, host) -> None:
        self._host = host
        # Registry methods run in worker threads and may overlap.
        self._state_lock = threading.RLock()
        self._load_lock = threading.Lock()

    def revoke_auth_token(self, token: str):
        """Server-side revocation of a presented auth token (TTL 24h).

        The revocation is persisted through the bound AuthService so a token
        signed with the persisted password hash cannot resurrect after an
        app restart.
        """
        if not token:
            return
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = time.time() + self._host._TOKEN_REVOCATION_TTL
        auth_service = getattr(self._host, "_auth_service", None)
        if auth_service is not None:
            try:
                # The durable write is authoritative.  Do not publish a
                # positive in-memory cache entry when it fails.
                auth_service.revoke_token(token, ttl=self._host._TOKEN_REVOCATION_TTL)
            except Exception as exc:
                # Fail closed immediately in this process while preserving the
                # distinction between a durable logout and a retryable error.
                with self._state_lock:
                    self._host._revoked_tokens[digest] = expires_at
                    self._prune_revoked_tokens_locked()
                raise TokenRevocationPersistenceError(
                    "Unable to persist token revocation"
                ) from exc
        with self._state_lock:
            self._host._revoked_tokens[digest] = expires_at
            self._prune_revoked_tokens_locked()

    def is_auth_token_revoked(self, token: str) -> bool:
        """Return True when a presented auth token has been revoked."""
        if not token:
            return False
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if not self._load_persisted_revocations():
            # Until the durable source has been read successfully, reject the
            # token rather than allowing an unknown persisted revocation to
            # authenticate during a database outage.
            return True
        with self._state_lock:
            expiry = self._host._revoked_tokens.get(digest)
            if expiry is not None:
                if expiry > time.time():
                    return True
                del self._host._revoked_tokens[digest]

        # A server may share the library database with another process.  The
        # in-memory table is only a positive cache, so a miss must consult the
        # durable source instead of treating a stale snapshot as authority.
        auth_service = getattr(self._host, "_auth_service", None)
        lookup = getattr(auth_service, "is_token_revoked", None)
        if not callable(lookup):
            return False
        try:
            return bool(lookup(token))
        except Exception:
            _log.warning("Persistent token revocation lookup failed", exc_info=True)
            return True

    def _load_persisted_revocations(self) -> bool:
        """Load persisted revocations, returning whether the load succeeded.

        The marker is set only after the durable source has been read.  A
        failed first read therefore remains retryable, while callers can fail
        closed until the durable revocation state is known.
        """
        host = self._host
        with self._state_lock:
            if getattr(host, "_revoked_loaded", False):
                return True
        # Only one worker may perform the initial durable read. Other workers
        # wait for it, then observe either the successful marker or retry after
        # a failed read.
        with self._load_lock:
            with self._state_lock:
                if getattr(host, "_revoked_loaded", False):
                    return True
            auth_service = getattr(host, "_auth_service", None)
            loader = getattr(auth_service, "load_active_revocations", None)
            if not callable(loader):
                # Legacy/headless hosts predate durable revocations. Preserve
                # their explicit compatibility contract.
                with self._state_lock:
                    host._revoked_loaded = True
                return True
            try:
                persisted = loader()
            except Exception:
                _log.warning("Persistent token revocation load failed", exc_info=True)
                return False
            with self._state_lock:
                for digest, expires_at in cast(
                        "dict[str, float]", persisted).items():
                    host._revoked_tokens.setdefault(digest, expires_at)
                self._prune_revoked_tokens_locked()
                host._revoked_loaded = True
            try:
                cast(Any, auth_service).prune_revocations()
            except Exception:
                _log.debug("Persistent token revocation prune failed", exc_info=True)
            return True

    def _prune_revoked_tokens(self) -> None:
        """Drop expired revocations; bound memory when the table grows large."""
        with self._state_lock:
            self._prune_revoked_tokens_locked()

    def _prune_revoked_tokens_locked(self) -> None:
        """Prune cache entries while ``_state_lock`` is held."""
        now = time.time()
        host = self._host
        expired = [
            digest for digest, expires_at in host._revoked_tokens.items()
            if expires_at <= now
        ]
        for digest in expired:
            del host._revoked_tokens[digest]
        # Evicted positive entries remain authoritative through the durable
        # miss lookup in is_auth_token_revoked.
        overflow = len(host._revoked_tokens) - host._TOKEN_REVOCATION_MAX
        if overflow > 0:
            for digest in sorted(
                host._revoked_tokens,
                key=lambda entry: host._revoked_tokens[entry],
            )[:overflow]:
                del host._revoked_tokens[digest]
