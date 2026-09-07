"""Keep process resource admission isolated between LAN tests."""
import pytest


@pytest.fixture(autouse=True)
def isolated_process_zip_budget(monkeypatch):
    from AssetsManager.lan import zip_resources

    # Direct handler tests may intentionally leave a response unprepared. Its
    # reservation must not affect unrelated cases; lifecycle tests explicitly
    # assert cleanup against the budget supplied to their own application.
    budget = zip_resources.ZipResourceBudget()
    monkeypatch.setattr(zip_resources, "_PROCESS_ZIP_BUDGET", budget)
    return budget


@pytest.fixture(autouse=True)
def isolated_process_zip_cleanup(monkeypatch):
    from AssetsManager.lan import zip_cleanup

    # Failed cleanup belongs to its test. Deterministic tests advance their
    # own clock instead of leaving a background daemon using patched I/O.
    service = zip_cleanup.ZipCleanupService(start_worker=False)
    monkeypatch.setattr(zip_cleanup, "_PROCESS_ZIP_CLEANUP", service)
    yield service
    service.close()
