from concurrent.futures import ThreadPoolExecutor

from AssetsManager.application.free_download_quota_service import (
    FreeDownloadQuotaConfig,
    FreeDownloadQuotaService,
)
from AssetsManager.repositories.free_download_quota_repository import (
    FreeDownloadQuotaRepository,
)


def test_repository_consumes_limit_and_rate_interval_atomically(schema_db):
    repository = FreeDownloadQuotaRepository(schema_db)

    first = repository.consume(
        "ip:127.0.0.1", 1_000, now=1_001.0, limit=2, min_interval_seconds=5,
    )
    assert first == {
        "allowed": True,
        "reason": None,
        "used": 1,
        "remaining": 1,
        "retry_after_seconds": 0,
        "last_download_at": 1_001.0,
    }

    limited = repository.consume(
        "ip:127.0.0.1", 1_000, now=1_003.0, limit=2, min_interval_seconds=5,
    )
    assert limited["allowed"] is False
    assert limited["reason"] == "rate_limited"
    assert limited["used"] == 1
    assert limited["remaining"] == 1
    assert limited["retry_after_seconds"] == 3

    second = repository.consume(
        "ip:127.0.0.1", 1_000, now=1_006.0, limit=2, min_interval_seconds=5,
    )
    assert second["allowed"] is True
    assert second["used"] == 2
    assert second["remaining"] == 0

    exhausted = repository.consume(
        "ip:127.0.0.1", 1_000, now=1_020.0, limit=2, min_interval_seconds=0,
    )
    assert exhausted["allowed"] is False
    assert exhausted["reason"] == "exhausted"
    assert exhausted["used"] == 2


def test_repository_cas_allows_only_one_concurrent_final_slot(schema_db):
    repository = FreeDownloadQuotaRepository(schema_db)

    def consume_once():
        return repository.consume(
            "ip:127.0.0.1", 1_000, now=1_001.0, limit=1, min_interval_seconds=0,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _index: consume_once(), range(4)))

    assert sum(bool(result["allowed"]) for result in results) == 1
    assert sum(result["reason"] == "exhausted" for result in results) == 3
    assert repository.get_window("ip:127.0.0.1", 1_000)["used"] == 1


def test_repository_prunes_only_current_identity_expired_windows(schema_db):
    repository = FreeDownloadQuotaRepository(schema_db)

    repository.consume(
        "anon:identity-a", 1_000, now=1_001.0, limit=5, min_interval_seconds=0,
    )
    repository.consume(
        "anon:identity-b", 1_000, now=1_001.0, limit=5, min_interval_seconds=0,
    )
    assert repository.get_window("anon:identity-a", 1_000)["used"] == 1
    assert repository.get_window("anon:identity-b", 1_000)["used"] == 1

    # Identity A advancing to a later window must not wipe identity B's rows.
    # Before the identity-scoped DELETE, this simulated one-identity consume
    # reset every other identity's persisted window.
    repository.consume(
        "anon:identity-a", 2_000, now=2_001.0, limit=5, min_interval_seconds=0,
    )
    assert repository.get_window("anon:identity-a", 1_000) is None
    assert repository.get_window("anon:identity-b", 1_000) is not None
    assert repository.get_window("anon:identity-b", 1_000)["used"] == 1


def test_service_exposes_disabled_and_period_scoped_info(schema_db):
    repository = FreeDownloadQuotaRepository(schema_db)
    now = [1_704_067_200.0]  # 2024-01-01 00:00:00 local time in common CI zones
    service = FreeDownloadQuotaService(repository, clock=lambda: now[0])

    disabled = service.info("ip:test", FreeDownloadQuotaConfig(enabled=False))
    assert disabled == {
        "enabled": False,
        "period": "daily",
        "limit": 0,
        "used": 0,
        "remaining": None,
        "reset_at": None,
        "min_interval_seconds": 0,
    }

    config = FreeDownloadQuotaConfig(enabled=True, period="daily", limit=3, min_interval_seconds=0)
    consumed = service.consume("ip:test", config)
    assert consumed["allowed"] is True
    assert consumed["info"]["used"] == 1
    assert consumed["info"]["remaining"] == 2

    now[0] += 24 * 60 * 60
    next_window = service.info("ip:test", config)
    assert next_window["used"] == 0
    assert next_window["remaining"] == 3
