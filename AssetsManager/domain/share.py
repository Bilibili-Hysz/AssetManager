"""Share link domain model."""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ShareLink:
    """Immutable representation of a share link.

    This is a pure domain value object with no infrastructure dependencies.
    """
    id: str
    paths: tuple[str, ...]
    created_by: str
    created_at: float
    expires_at: float | None = None
    max_downloads: int | None = None
    download_count: int = 0
    allow_preview: bool = True
    has_password: bool = False

    def is_expired(self) -> bool:
        """Check if this share link has expired."""
        return self.expires_at is not None and time.time() > self.expires_at

    def is_download_limit_reached(self) -> bool:
        """Check if the download limit has been reached."""
        return self.max_downloads is not None and self.download_count >= self.max_downloads

    def can_download(self) -> bool:
        """Check if downloading is allowed (not expired, not over limit)."""
        return not self.is_expired() and not self.is_download_limit_reached()

    def is_path_allowed(self, rel_path: str) -> bool:
        """Check if a relative path falls within this share's scope."""
        for sp in self.paths:
            if sp == rel_path or rel_path.startswith(sp + "/"):
                return True
        return False

    @classmethod
    def from_db_row(cls, row: dict) -> ShareLink:
        """Create a ShareLink from a database row dict.

        The row format matches the output of ShareRepository.get().
        """
        return cls(
            id=row.get("id", ""),
            paths=tuple(row.get("paths", [])),
            created_by=row.get("created_by", ""),
            created_at=row.get("created_at", 0.0),
            expires_at=row.get("expires_at"),
            max_downloads=row.get("max_downloads"),
            download_count=row.get("download_count", 0),
            allow_preview=row.get("allow_preview", True),
            has_password=bool(row.get("password_hash")),
        )

    def to_public_dict(self) -> dict:
        """Return a dict safe for public API responses (no sensitive fields)."""
        result = {
            "id": self.id,
            "paths": list(self.paths),
            "created_by": self.created_by,
            "created_at": self.created_at,
            "allow_preview": self.allow_preview,
            "download_count": self.download_count,
            "max_downloads": self.max_downloads,
            "has_password": self.has_password,
        }
        if self.expires_at is not None:
            remaining = self.expires_at - time.time()
            result["expired"] = remaining <= 0
            result["expires_in_hours"] = max(0, round(remaining / 3600, 1))
        else:
            result["expired"] = False
            result["expires_in_hours"] = None
        return result
