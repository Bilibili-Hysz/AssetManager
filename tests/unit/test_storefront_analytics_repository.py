from __future__ import annotations

import sqlite3

import pytest

from AssetsManager.repositories.storefront_analytics_repository import StorefrontAnalyticsRepository


@pytest.fixture()
def repo() -> StorefrontAnalyticsRepository:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(
        """
        CREATE TABLE shop_storefront_view_days (
            day TEXT PRIMARY KEY,
            view_count INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        );
        CREATE TABLE shop_storefront_view_visitors (
            day TEXT NOT NULL,
            visitor_hash TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (day, visitor_hash)
        );
        """
    )
    return StorefrontAnalyticsRepository(conn)


def test_record_unique_view_deduplicates_each_visitor_per_day(repo: StorefrontAnalyticsRepository):
    visitor_a = "a" * 64
    visitor_b = "b" * 64

    assert repo.record_unique_view_and_prune("2026-08-07", visitor_a, "2026-08-06", recorded_at=1.0) is True
    assert repo.record_unique_view_and_prune("2026-08-07", visitor_a, "2026-08-06", recorded_at=2.0) is False
    assert repo.record_unique_view_and_prune("2026-08-07", visitor_b, "2026-08-06", recorded_at=3.0) is True

    assert repo.daily_views("2026-08-07") == 2
    assert repo.total_views() == 2


def test_pruning_deduplication_hashes_preserves_aggregate_counts(repo: StorefrontAnalyticsRepository):
    assert repo.record_unique_view_and_prune("2026-08-05", "a" * 64, "2026-08-05", recorded_at=1.0)
    assert repo.record_unique_view_and_prune("2026-08-06", "b" * 64, "2026-08-05", recorded_at=2.0)
    assert repo.record_unique_view_and_prune("2026-08-07", "c" * 64, "2026-08-06", recorded_at=3.0)

    retained = repo._conn.execute(
        "SELECT day FROM shop_storefront_view_visitors ORDER BY day"
    ).fetchall()
    assert retained == [("2026-08-06",), ("2026-08-07",)]
    assert repo.total_views() == 3


def test_repository_rejects_malformed_days_and_hashes(repo: StorefrontAnalyticsRepository):
    with pytest.raises(ValueError, match="ISO calendar"):
        repo.record_unique_view("2026/08/07", "a" * 64)
    with pytest.raises(ValueError, match="SHA-256"):
        repo.record_unique_view("2026-08-07", "not-a-hash")

def test_record_and_prune_roll_back_together_on_prune_failure(repo: StorefrontAnalyticsRepository):
    assert repo.record_unique_view("2026-08-06", "a" * 64, recorded_at=1.0) is True
    repo._conn.executescript(
        """
        CREATE TRIGGER fail_storefront_prune
        BEFORE DELETE ON shop_storefront_view_visitors
        WHEN OLD.day < '2026-08-06'
        BEGIN
            SELECT RAISE(ABORT, 'prune failed');
        END;
        INSERT INTO shop_storefront_view_visitors(day, visitor_hash, created_at)
        VALUES ('2026-08-05', 'b' || printf('%064d', 0), 2.0);
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="prune failed"):
        repo.record_unique_view_and_prune("2026-08-07", "c" * 64, "2026-08-06", recorded_at=3.0)

    assert repo.daily_views("2026-08-07") == 0
    assert repo._conn.execute(
        "SELECT COUNT(*) FROM shop_storefront_view_visitors WHERE day='2026-08-05'"
    ).fetchone()[0] == 1
