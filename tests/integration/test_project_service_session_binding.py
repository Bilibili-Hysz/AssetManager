"""ProjectService session-bound cache construction regressions."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from AssetsManager.application.project_service import ProjectDepthConfig, ProjectService


class _SessionProbe:
    @contextmanager
    def operation(self):
        yield


def test_project_service_binds_directory_cache_to_current_session(tmp_path, schema_db, monkeypatch):
    import importlib

    project_module = importlib.import_module("AssetsManager.application.project_service")
    library = tmp_path / "library"
    library.mkdir()
    (library / "alpha").mkdir()

    session = _SessionProbe()
    observed_sessions = []
    real_cache = project_module.DirectoryCache

    class SpyDirectoryCache(real_cache):
        def __init__(self, *args, **kwargs):
            observed_sessions.append(kwargs.get("session"))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(project_module, "DirectoryCache", SpyDirectoryCache)

    ProjectService(
        connection_provider=lambda _root: schema_db,
        session=session,
    ).get_home(
        library,
        depth_config=ProjectDepthConfig(global_depth=1),
        db_conn=schema_db,
    )

    assert observed_sessions == [session]


def test_session_bound_project_service_rejects_after_session_close(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        service = bootstrap.runtime_for(session).services.project_service
        session.close()
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            service.get_home(session.root)
    finally:
        bootstrap.library_service.close()
