"""Policy layer for the ordinary library-download quota.

Commerce delivery tokens have a separate quota model.  This service owns the
periodic free-download policy used only by ``/api/download`` and its batch
counterpart.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from AssetsManager.repositories.free_download_quota_repository import (
    FreeDownloadQuotaRepository,
)


@dataclass(frozen=True)
class FreeDownloadQuotaConfig:
    enabled: bool = False
    period: str = "daily"
    limit: int = 20
    min_interval_seconds: int = 5

    def normalized(self) -> "FreeDownloadQuotaConfig":
        period = "weekly" if str(self.period).lower() == "weekly" else "daily"
        try:
            limit = int(self.limit)
        except (TypeError, ValueError):
            limit = 20
        try:
            interval = int(self.min_interval_seconds)
        except (TypeError, ValueError):
            interval = 5
        if limit <= 0:
            limit = 20
        return FreeDownloadQuotaConfig(
            enabled=bool(self.enabled),
            period=period,
            limit=min(limit, 1_000_000),
            min_interval_seconds=max(0, min(interval, 86_400)),
        )


class FreeDownloadQuotaService:
    def __init__(self, repository: FreeDownloadQuotaRepository, *, clock=time.time) -> None:
        self.repository = repository
        self.clock = clock

    @classmethod
    def for_connection(
        cls,
        connection,
        *,
        library_root=None,
        session=None,
        clock=time.time,
    ) -> "FreeDownloadQuotaService":
        """Build a library-bound service without leaking repository wiring to routes."""
        return cls(
            FreeDownloadQuotaRepository(
                connection,
                library_root=library_root,
                session=session,
            ),
            clock=clock,
        )

    @staticmethod
    def period_start(now: float, period: str) -> int:
        local = datetime.fromtimestamp(float(now))
        day = local.replace(hour=0, minute=0, second=0, microsecond=0)
        if str(period).lower() == "weekly":
            day -= timedelta(days=day.weekday())
        return int(day.timestamp())

    @classmethod
    def reset_at(cls, now: float, period: str) -> int:
        start = cls.period_start(now, period)
        length = timedelta(days=7 if str(period).lower() == "weekly" else 1)
        return int((datetime.fromtimestamp(start) + length).timestamp())

    @staticmethod
    def _identity(identity_key: str) -> str:
        return str(identity_key).strip() or "ip:unknown"

    def info(self, identity_key: str, config: FreeDownloadQuotaConfig) -> dict[str, Any]:
        cfg = config.normalized()
        now = float(self.clock())
        if not cfg.enabled:
            return {
                "enabled": False,
                "period": cfg.period,
                "limit": 0,
                "used": 0,
                "remaining": None,
                "reset_at": None,
                "min_interval_seconds": 0,
            }
        start = self.period_start(now, cfg.period)
        row = self.repository.get_window(self._identity(identity_key), start)
        used = int(row["used"]) if row is not None else 0
        return {
            "enabled": True,
            "period": cfg.period,
            "limit": cfg.limit,
            "used": used,
            "remaining": max(0, cfg.limit - used),
            "reset_at": self.reset_at(now, cfg.period),
            "min_interval_seconds": cfg.min_interval_seconds,
        }

    def consume(self, identity_key: str, config: FreeDownloadQuotaConfig) -> dict[str, Any]:
        cfg = config.normalized()
        now = float(self.clock())
        if not cfg.enabled:
            return {
                "allowed": True,
                "reason": None,
                "info": self.info(identity_key, cfg),
                "retry_after_seconds": 0,
            }
        result = self.repository.consume(
            self._identity(identity_key),
            self.period_start(now, cfg.period),
            now=now,
            limit=cfg.limit,
            min_interval_seconds=cfg.min_interval_seconds,
        )
        info = {
            "enabled": True,
            "period": cfg.period,
            "limit": cfg.limit,
            "used": int(result["used"]),
            "remaining": int(result["remaining"]),
            "reset_at": self.reset_at(now, cfg.period),
            "min_interval_seconds": cfg.min_interval_seconds,
        }
        return {
            "allowed": bool(result["allowed"]),
            "reason": result.get("reason"),
            "info": info,
            "retry_after_seconds": int(result.get("retry_after_seconds", 0)),
        }
