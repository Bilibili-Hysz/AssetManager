"""Share link application service.

Encapsulates all share link business logic. Uses domain types for
type safety and ShareRepository for persistence.
"""
from __future__ import annotations

import logging
import math
import secrets
import threading
import string
import time
from pathlib import Path
from sqlite3 import Connection
from typing import TYPE_CHECKING

from AssetsManager.application.context import session_operation

from AssetsManager.domain import auth as auth_crypto
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.errors import ValidationError
from AssetsManager.domain.events import ShareChanged
from AssetsManager.domain.share import ShareLink
from AssetsManager.repositories.share_repository import ShareRepository

_log = logging.getLogger(__name__)
_MISSING_PROVIDER = object()

if TYPE_CHECKING:
    from AssetsManager.application.context import LibrarySession


class ShareService:
    """Share link lifecycle management using ShareRepository."""

    # Brute-force guard: after this many consecutive failed password
    # verifications, attempts are refused (429) for the cooldown window.
    MAX_PASSWORD_FAILURES = 5
    PASSWORD_COOLDOWN_SECONDS = 60.0

    def __init__(
        self,
        db_conn: Connection,
        token_secret: str,
        *,
        session: LibrarySession | None = None,
    ):
        self._conn = db_conn
        self._secret = token_secret
        self._session = None
        self._repo = ShareRepository(db_conn)
        self._binding_lock = threading.RLock()
        self._event_bus = get_event_bus()
        self._library_root = ""
        self._session_token = ""
        self._password_failures: dict[str, list[float]] = {}
        self._password_failures_lock = threading.Lock()
        if session is not None:
            self._bind_session(session)

    def _bind_session(self, session: LibrarySession) -> None:
        with self._binding_lock:
            if self._session is not None:
                if self._session is session:
                    return
                raise RuntimeError(
                    "ShareService is already bound to another LibrarySession"
                )

            connection_for = getattr(session, "connection_for", _MISSING_PROVIDER)
            if connection_for is _MISSING_PROVIDER:
                # Explicit legacy compatibility: historical fake sessions omit
                # the canonical provider entirely.  Malformed provider values
                # must not silently downgrade into this raw compatibility path.
                if not callable(getattr(session, "operation", None)):
                    raise TypeError("Legacy session must provide callable operation()")
                root_value = getattr(session, "root_str", None)
                if root_value is None:
                    root_value = getattr(session, "root", None)
                if root_value is None:
                    raise TypeError("Legacy session must provide root or root_str")

                with session.operation():
                    bound_repository = ShareRepository(self._conn)
                    library_root = str(root_value)
                    session_token = getattr(session, "event_token", "")
                    self._publish_session_binding(
                        session, bound_repository, library_root, session_token
                    )
                return

            if not callable(connection_for):
                raise TypeError(
                    "Canonical LibrarySession must provide callable connection_for()"
                )
            if not callable(getattr(session, "operation", None)):
                raise TypeError("Canonical LibrarySession must provide operation()")
            requested_root = getattr(session, "root", None)
            if requested_root is None:
                requested_root = getattr(session, "root_str", None)
            if requested_root is None:
                raise TypeError("Canonical LibrarySession must provide root or root_str")

            with session.operation():
                session_connection = session.connection_for(requested_root)
                if session_connection is not self._conn:
                    raise ValueError(
                        "ShareService connection does not belong to the LibrarySession"
                    )
                bound_repository = ShareRepository.for_session(session)
                library_root = getattr(session, "root_str", str(requested_root))
                session_token = getattr(session, "event_token", "")
                self._publish_session_binding(
                    session, bound_repository, library_root, session_token
                )

    def _publish_session_binding(
        self,
        session: LibrarySession,
        repository: ShareRepository,
        library_root: str,
        session_token: str,
    ) -> None:
        def publish_binding() -> None:
            # `_session` is the readiness flag read by `session_operation`, so
            # publish every accompanying field before it.
            self._repo = repository
            self._library_root = library_root
            self._session_token = session_token
            self._session = session

        publish_while_live = getattr(session, "_publish_while_live", None)
        if callable(publish_while_live):
            publish_while_live(publish_binding)
        else:
            publish_binding()

    @staticmethod
    def validate_password(value: object) -> str | None:
        """Validate a share password and normalize an empty string to no password."""
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValidationError("password", "Invalid password format")
        # Minimum 8 characters.  ``auth.validate_password_strength`` offers a
        # stricter composition policy; share links deliberately stay at the
        # length floor so short-but-strong shared secrets keep working.
        if len(value) < 8:
            raise ValidationError("password", "Password must be at least 8 characters")
        if len(value) > 128:
            raise ValidationError("password", "Password must be less than 128 characters")
        return value

    @staticmethod
    def validate_expires_hours(value: object) -> int | None:
        """Validate an optional expiry in hours."""
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError("expires_hours", "Invalid expiry format")
        if value < 1 or value > 8760:
            raise ValidationError("expires_hours", "Expiry must be between 1 and 8760 hours")
        return value

    @staticmethod
    def validate_max_downloads(value: object) -> int | None:
        """Validate an optional download limit."""
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError("max_downloads", "Invalid max downloads format")
        if value < 1 or value > 10000:
            raise ValidationError("max_downloads", "Max downloads must be between 1 and 10000")
        return value

    def _publish_changed(self) -> None:
        if self._library_root and self._session_token:
            try:
                self._event_bus.publish(ShareChanged(
                    library_root=self._library_root,
                    session_token=self._session_token,
                ))
            except Exception:
                _log.exception("Share projection notification failed")

    def _validate_paths(self, paths: list[str]) -> list[str]:
        """Validate share paths and normalize paths for bound library sessions.

        Unbound services are retained for legacy callers and tests that use
        virtual paths.  A session-bound service, however, must only persist
        existing paths inside its library and stores them as stable relative
        POSIX-style keys.
        """
        if not isinstance(paths, list) or not paths:
            raise ValidationError("paths", "No paths provided")
        if len(paths) > 100:
            raise ValidationError("paths", "Too many paths (max 100)")

        if self._session is None:
            return paths

        root = Path(self._library_root).resolve()
        normalized: list[str] = []
        for raw_path in paths:
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValidationError("paths", "No valid paths")

            candidate_path = Path(raw_path)
            if not candidate_path.is_absolute():
                candidate_path = root / candidate_path

            try:
                candidate = candidate_path.resolve()
            except (OSError, RuntimeError, ValueError):
                raise ValidationError("paths", "No valid paths") from None

            if not candidate.is_relative_to(root):
                raise ValidationError("paths", "Path escape detected")
            if not candidate.exists():
                raise ValidationError("paths", "No valid paths")

            relative = candidate.relative_to(root).as_posix()
            normalized.append(relative or ".")

        return normalized

    @session_operation
    def init_table(self) -> None:
        """Initialize the share-link persistence schema."""
        self._repo.init_table()

    # ── CRUD ────────────────────────────────────────────────────

    @session_operation
    def create_share(
        self,
        paths: list[str],
        password: str | None = None,
        expires_hours: int | None = None,
        max_downloads: int | None = None,
        allow_preview: bool = True,
        created_by: str | None = None,
    ) -> ShareLink | None:
        """Create a new share link. Returns ShareLink or None on failure."""
        paths = self._validate_paths(paths)
        password = self.validate_password(password)
        expires_hours = self.validate_expires_hours(expires_hours)
        max_downloads = self.validate_max_downloads(max_downloads)

        share_id = self._generate_share_id()
        for _ in range(5):
            if self._repo.get(share_id) is None:
                break
            share_id = self._generate_share_id()

        password_hash = auth_crypto.hash_password(password) if password else None
        expires_at = (time.time() + expires_hours * 3600) if expires_hours is not None else None

        ok = self._repo.insert(share_id, paths, password_hash, expires_at, max_downloads, allow_preview, created_by)
        if not ok:
            return None

        self._publish_changed()

        return ShareLink(
            id=share_id,
            paths=tuple(paths),
            created_by=created_by or "",
            created_at=time.time(),
            expires_at=expires_at,
            max_downloads=max_downloads,
            download_count=0,
            allow_preview=allow_preview,
            has_password=password_hash is not None,
        )

    @session_operation
    def get_share(self, share_id: str) -> ShareLink | None:
        """Get a share link by ID. Returns ShareLink or None if not found."""
        raw = self._repo.get(share_id)
        if raw is None:
            return None
        return ShareLink.from_db_row(raw)

    @session_operation
    def get_share_record(self, share_id: str) -> ShareLink | None:
        """Get a share link even if it is expired or over its download limit."""
        raw = self._repo.get(share_id, include_unavailable=True)
        if raw is None:
            return None
        return ShareLink.from_db_row(raw)

    @session_operation
    def list_shares(self, created_by: str | None = None) -> list[ShareLink]:
        """List share links, optionally filtered by creator."""
        raw_list = self._repo.list_all(created_by)
        return [ShareLink.from_db_row(r) for r in raw_list]

    @session_operation
    def delete_share(self, share_id: str) -> bool:
        """Delete a share link. Returns True if deleted."""
        ok = self._repo.delete(share_id)
        if ok:
            self._publish_changed()
        return ok

    # ── Authentication ──────────────────────────────────────────

    @session_operation
    def verify_password(self, share_id: str, password: str) -> bool:
        """Verify a share link's password.

        Both the success and failure paths run the full PBKDF2 verification
        (``auth.verify_password`` always hashes before comparing), so timing
        does not reveal whether a guess was correct.  Callers should gate on
        :meth:`password_attempt_blocked` first to refuse brute force.
        """
        pw_hash = self._repo.get_password_hash(share_id)
        if pw_hash is None:
            return True  # No password required
        if not auth_crypto.verify_password(password, pw_hash):
            return False
        self._migrate_password_cost(share_id, password, pw_hash)
        return True

    def _migrate_password_cost(
        self, share_id: str, password: str, stored_hash: str
    ) -> None:
        """Re-stamp a legacy/low-cost share hash at the current PBKDF2 cost.

        Runs only after a successful verification, the one moment the
        plaintext is available.  A failure here must not fail the
        verification: the visitor is already authorized and the old hash
        still verifies, so the migration retries on the next attempt.
        """
        if not auth_crypto.needs_password_rehash(stored_hash):
            return
        try:
            self._repo.set_password_hash(share_id, auth_crypto.hash_password(password))
        except Exception:
            _log.warning(
                "Share password cost migration failed for %s; access stands",
                share_id, exc_info=True,
            )

    # ── Brute-force protection ──────────────────────────────────

    def password_attempt_blocked(self, share_id: str) -> int:
        """Return seconds remaining in the lockout window, or 0 if allowed.

        In-process per-share guard: after ``MAX_PASSWORD_FAILURES``
        consecutive failed password verifications, attempts are refused for
        ``PASSWORD_COOLDOWN_SECONDS``.  The window slides, so once the
        cooldown has fully elapsed the counter resets on its own.
        """
        with self._password_failures_lock:
            now = time.time()
            stamps = [
                ts for ts in self._password_failures.get(share_id, [])
                if now - ts < self.PASSWORD_COOLDOWN_SECONDS
            ]
            if stamps:
                self._password_failures[share_id] = stamps
            else:
                self._password_failures.pop(share_id, None)
            if len(stamps) >= self.MAX_PASSWORD_FAILURES:
                return max(1, math.ceil(self.PASSWORD_COOLDOWN_SECONDS - (now - stamps[0])))
            return 0

    def record_password_failure(self, share_id: str) -> None:
        """Record a failed password verification for brute-force tracking."""
        with self._password_failures_lock:
            now = time.time()
            stamps = [
                ts for ts in self._password_failures.get(share_id, [])
                if now - ts < self.PASSWORD_COOLDOWN_SECONDS
            ]
            stamps.append(now)
            self._password_failures[share_id] = stamps
            # Opportunistic global sweep: shares whose newest failure left
            # the cooldown window can never block again, so drop those keys
            # instead of retaining one entry per share ever probed.
            expired = [
                other_id
                for other_id, other_stamps in self._password_failures.items()
                if not other_stamps
                or now - max(other_stamps) >= self.PASSWORD_COOLDOWN_SECONDS
            ]
            for other_id in expired:
                self._password_failures.pop(other_id, None)

    def reset_password_failures(self, share_id: str) -> None:
        """Clear the failure counter after a successful verification."""
        with self._password_failures_lock:
            self._password_failures.pop(share_id, None)

    @session_operation
    def generate_token(self, share_id: str) -> str:
        """Generate a time-limited share access token."""
        return auth_crypto.generate_share_token(share_id, self._secret)

    @session_operation
    def verify_token(self, token: str, share_id: str) -> bool:
        """Verify a share access token."""
        return auth_crypto.verify_share_token(token, share_id, self._secret)

    # ── Downloads ───────────────────────────────────────────────

    @session_operation
    def increment_download(self, share_id: str) -> bool:
        """Increment the download counter for a share link."""
        ok = self._repo.increment_download(share_id)
        if ok:
            self._publish_changed()
        return ok

    # ── Validation helpers ──────────────────────────────────────

    @session_operation
    def validate_access(
        self,
        share_id: str,
        rel_path: str,
        token: str | None = None,
    ) -> tuple[ShareLink | None, str]:
        """Validate that a share exists, is accessible, and the path is allowed.

        Single source of truth for the public share admission checks
        (existence, password token, expiry, download limit, path scope).
        ``lan/routes/shares.py: handle_share_download`` calls this and keeps
        only the filesystem resolution (``_resolve_share_target``) inline —
        keep the two in sync.

        Returns ``(share, "")`` on success; otherwise a share (may be None)
        plus an error string: "Share not found", "Unauthorized",
        "Share expired", "Download limit reached", "File not in share scope".
        """
        share = self.get_share_record(share_id)
        if share is None:
            return None, "Share not found"

        if share.has_password:
            if not token or not self.verify_token(token, share_id):
                return None, "Unauthorized"

        if not share.can_download():
            if share.is_expired():
                return share, "Share expired"
            return share, "Download limit reached"

        if not share.is_path_allowed(rel_path):
            return share, "File not in share scope"

        return share, ""

    @staticmethod
    def _generate_share_id(length: int = 10) -> str:
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))
