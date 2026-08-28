"""Policy layer for the ordinary library-download quota.

Commerce delivery tokens have a separate quota model.  This service owns the
periodic free-download policy used only by the LAN download endpoint and its
batch counterpart.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import QuotaChanged
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
    MAINTENANCE_INTERVAL_SECONDS = 60 * 60
    MAINTENANCE_FAILURE_RETRY_SECONDS = 30

    def __init__(
        self,
        repository: FreeDownloadQuotaRepository,
        *,
        clock=time.time,
        monotonic_clock=time.monotonic,
        session: Any | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock
        self.monotonic_clock = monotonic_clock
        self._session = session
        self._maintenance_lock = threading.RLock()
        self._maintenance_last_success: float | None = None
        self._maintenance_next_attempt = 0.0

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
            session=session,
        )

    @staticmethod
    def period_start(now: float, period: str) -> int:
        # Quota windows deliberately follow the host's local calendar, so a
        # daily quota resets at the operator's midnight rather than UTC's.
        local = datetime.fromtimestamp(float(now))  # noqa: DTZ006
        day = local.replace(hour=0, minute=0, second=0, microsecond=0)
        if str(period).lower() == "weekly":
            day -= timedelta(days=day.weekday())
        return int(day.timestamp())

    @classmethod
    def reset_at(cls, now: float, period: str) -> int:
        start = cls.period_start(now, period)
        length = timedelta(days=7 if str(period).lower() == "weekly" else 1)
        # Local calendar again, matching period_start.
        return int((datetime.fromtimestamp(start) + length).timestamp())  # noqa: DTZ006

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
        if bool(result.get("allowed")) and self._session is not None:
            # Only an actual deduction invalidates the quota projection; a
            # rejected consume (exhausted / rate-limited) changed no state.
            get_event_bus().publish(QuotaChanged(
                library_root=self._session.root_str,
                session_token=self._session.event_token,
                name=self._identity(identity_key),
            ))
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

    def prune_stale_windows(
        self,
        config: FreeDownloadQuotaConfig,
        *,
        now: float | None = None,
        periods_to_keep: int = 2,
    ) -> int:
        """Opportunistically delete windows older than the kept periods.

        The cutoff walks back from the current period boundary, so a clock
        fault shorter than ``periods_to_keep`` periods cannot reach an
        active bucket and a rolled-back clock only shrinks (never widens)
        the deleted range.  Intended as opportunistic maintenance outside
        the consume hot path.
        """
        if periods_to_keep < 1:
            raise ValueError("periods_to_keep must be >= 1")
        cfg = config.normalized()
        timestamp = float(self.clock()) if now is None else float(now)
        period_days = 7 if str(cfg.period).lower() == "weekly" else 1
        cutoff_base = timestamp - periods_to_keep * period_days * 86_400
        before = self.period_start(cutoff_base, cfg.period)
        return self.repository.prune_windows(before)

    def maybe_prune_stale_windows(
        self,
        config: FreeDownloadQuotaConfig,
        *,
        now: float | None = None,
    ) -> int | None:
        """Run bounded opportunistic maintenance when its gate is due.

        The gate is process-local and advisory: concurrent LAN processes may
        each perform the same idempotent prune, while a transient failure gets
        a short retry window instead of suppressing maintenance for the rest of
        the service lifetime.
        """
        if not config.normalized().enabled:
            return None
        monotonic_now = float(self.monotonic_clock())
        with self._maintenance_lock:
            if monotonic_now < self._maintenance_next_attempt:
                return None
            try:
                removed = self.prune_stale_windows(config, now=now)
            except Exception:
                self._maintenance_next_attempt = (
                    monotonic_now + self.MAINTENANCE_FAILURE_RETRY_SECONDS
                )
                raise
            self._maintenance_last_success = monotonic_now
            self._maintenance_next_attempt = (
                monotonic_now + self.MAINTENANCE_INTERVAL_SECONDS
            )
            return removed
