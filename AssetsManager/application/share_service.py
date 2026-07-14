"""Share link application service.

Encapsulates all share link business logic. Uses domain types for
type safety and ShareRepository for persistence.
"""
from __future__ import annotations

import logging
import secrets
import string
import time
from sqlite3 import Connection

from AssetsManager.domain import auth as auth_crypto
from AssetsManager.domain.share import ShareLink
from AssetsManager.repositories.share_repository import ShareRepository

_log = logging.getLogger(__name__)


class ShareService:
    """Share link lifecycle management using ShareRepository."""

    def __init__(self, db_conn: Connection, token_secret: str):
        self._conn = db_conn
        self._secret = token_secret
        self._repo = ShareRepository(db_conn)

    # ── CRUD ────────────────────────────────────────────────────

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
        share_id = self._generate_share_id()
        for _ in range(5):
            if self._repo.get(share_id) is None:
                break
            share_id = self._generate_share_id()

        password_hash = auth_crypto.hash_password(password) if password else None
        expires_at = (time.time() + expires_hours * 3600) if expires_hours else None

        ok = self._repo.insert(share_id, paths, password_hash, expires_at, max_downloads, allow_preview, created_by)
        if not ok:
            return None

        return ShareLink(
            id=share_id,
            paths=tuple(paths),
            created_by=created_by or "",
            created_at=time.time(),
            expires_at=expires_at,
            max_downloads=max_downloads,
            download_count=0,
            allow_preview=allow_preview,
            has_password=password is not None,
        )

    def get_share(self, share_id: str) -> ShareLink | None:
        """Get a share link by ID. Returns ShareLink or None if not found."""
        raw = self._repo.get(share_id)
        if raw is None:
            return None
        return ShareLink.from_db_row(raw)

    def get_share_record(self, share_id: str) -> ShareLink | None:
        """Get a share link even if it is expired or over its download limit."""
        raw = self._repo.get(share_id, include_unavailable=True)
        if raw is None:
            return None
        return ShareLink.from_db_row(raw)

    def list_shares(self, created_by: str | None = None) -> list[ShareLink]:
        """List share links, optionally filtered by creator."""
        raw_list = self._repo.list_all(created_by)
        return [ShareLink.from_db_row(r) for r in raw_list]

    def delete_share(self, share_id: str) -> bool:
        """Delete a share link. Returns True if deleted."""
        return self._repo.delete(share_id)

    # ── Authentication ──────────────────────────────────────────

    def verify_password(self, share_id: str, password: str) -> bool:
        """Verify a share link's password."""
        pw_hash = self._repo.get_password_hash(share_id)
        if pw_hash is None:
            return True  # No password required
        return auth_crypto.verify_password(password, pw_hash)

    def generate_token(self, share_id: str) -> str:
        """Generate a time-limited share access token."""
        return auth_crypto.generate_share_token(share_id, self._secret)

    def verify_token(self, token: str, share_id: str) -> bool:
        """Verify a share access token."""
        return auth_crypto.verify_share_token(token, share_id, self._secret)

    # ── Downloads ───────────────────────────────────────────────

    def increment_download(self, share_id: str) -> bool:
        """Increment the download counter for a share link."""
        return self._repo.increment_download(share_id)

    # ── Validation helpers ──────────────────────────────────────

    def validate_access(
        self,
        share_id: str,
        rel_path: str,
        token: str | None = None,
    ) -> tuple[ShareLink | None, str]:
        """Validate that a share exists, is accessible, and the path is allowed."""
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
