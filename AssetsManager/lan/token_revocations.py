"""Auth-token revocation registry for the LAN server.

Moved from ``lan/server.py``.  The registry is *host-bound*: it stores its
in-memory revocation table on the host server (``host._revoked_tokens`` /
``host._revoked_loaded``) so the existing skeleton-test pattern that assigns
those attributes directly keeps working unchanged.  The only behavior change is
where the methods live; the logic is identical.

Concurrency contract (unchanged): only the server event-loop thread reads or
writes the revocation table (auth middleware + logout handler).
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import cast

_log = logging.getLogger(__name__)


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
        self._host._revoked_tokens[digest] = expires_at
        auth_service = getattr(self._host, "_auth_service", None)
        if auth_service is not None:
            try:
                auth_service.revoke_token(token, ttl=self._host._TOKEN_REVOCATION_TTL)
            except Exception:
                # In-memory revocation still holds for this process; log and
                # keep going rather than failing the logout response.
                _log.warning("Persistent token revocation write failed", exc_info=True)

    def is_auth_token_revoked(self, token: str) -> bool:
        """Return True when a presented auth token has been revoked."""
        if not token:
            return False
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self._load_persisted_revocations()
        expiry = self._host._revoked_tokens.get(digest)
        if expiry is None:
            return False
        if expiry <= time.time():
            del self._host._revoked_tokens[digest]
            return False
        if len(self._host._revoked_tokens) > self._host._TOKEN_REVOCATION_MAX:
            self._prune_revoked_tokens()
        return True

    def _load_persisted_revocations(self) -> None:
        """Load revocations persisted by earlier processes, once per server.

        The in-memory table is the hot-path positive cache; the library DB
        (via the bound AuthService) is the durable source of truth across
        app restarts.
        """
        host = self._host
        if getattr(host, "_revoked_loaded", False):
            return
        host._revoked_loaded = True
        auth_service = getattr(host, "_auth_service", None)
        if auth_service is None:
            return
        try:
            persisted = auth_service.load_active_revocations()
        except Exception:
            _log.warning("Persistent token revocation load failed", exc_info=True)
            return
        for digest, expires_at in persisted.items():
            host._revoked_tokens.setdefault(digest, expires_at)
        # Best-effort DB hygiene: drop rows whose TTL already passed.
        try:
            auth_service.prune_revocations()
        except Exception:
            pass

    def _prune_revoked_tokens(self) -> None:
        """Drop expired revocations; bound memory when the table grows large."""
        now = time.time()
        host = self._host
        expired = [
            digest for digest, expires_at in host._revoked_tokens.items()
            if expires_at <= now
        ]
        for digest in expired:
            del host._revoked_tokens[digest]
        # The table is still large after pruning (mass revocation burst);
        # drop oldest entries to keep memory bounded.
        if len(host._revoked_tokens) > host._TOKEN_REVOCATION_MAX:
            for digest in sorted(
                host._revoked_tokens,
                key=lambda entry: cast(float, host._revoked_tokens[entry]),
            )[: len(host._revoked_tokens) - host._TOKEN_REVOCATION_MAX]:
                del host._revoked_tokens[digest]
