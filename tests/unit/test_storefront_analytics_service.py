from __future__ import annotations

from AssetsManager.application.storefront_analytics_service import StorefrontAnalyticsService


class AnalyticsRepo:
    def __init__(self) -> None:
        self.recorded: list[tuple[str, str, str, float]] = []

    def record_unique_view_and_prune(
        self, day: str, visitor_hash: str, prune_before: str, *, recorded_at: float
    ) -> bool:
        self.recorded.append((day, visitor_hash, prune_before, recorded_at))
        return True

    def total_views(self) -> int:
        return 42


def test_service_hashes_browser_token_and_keeps_current_and_previous_utc_days():
    repo = AnalyticsRepo()
    service = StorefrontAnalyticsService(repository=repo)

    assert service.record_storefront_view(".", "a" * 32, now=1_786_060_800.0) is True

    day, token_hash, prune_before, recorded_at = repo.recorded[0]
    assert day == "2026-08-07"
    assert token_hash != "a" * 32
    assert len(token_hash) == 64
    assert prune_before == "2026-08-06"
    assert recorded_at == 1_786_060_800.0


def test_service_exposes_only_aggregate_store_view_count():
    service = StorefrontAnalyticsService(repository=AnalyticsRepo())
    assert service.stats(".") == {"store_views": 42}
