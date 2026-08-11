"""Canonical session binding for legacy core stores."""

from __future__ import annotations

import sqlite3

import pytest

from AssetsManager.application import ApplicationBootstrap
from AssetsManager.core.project_data import ProjectData
from AssetsManager.core.tag_store import TagStore


def test_library_service_binds_session_to_context_core_stores(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        assert session.context.project_data._session is session
        assert session.context.tag_store._session is session
    finally:
        bootstrap.library_service.close()


def test_session_aware_core_store_constructors_use_session_connection(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        project_data = ProjectData(str(session.root), session=session)
        tag_store = TagStore(str(session.root), session=session)

        assert project_data._db is session.connection_for(session.root)
        assert tag_store._db is session.connection_for(session.root)
        assert project_data._session is session
        assert tag_store._session is session

        session.close()
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            project_data.get_notes(str(session.root / "asset.txt"))
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            tag_store.get_all_tags()
    finally:
        bootstrap.library_service.close()


def test_session_aware_core_store_rejects_unmanaged_foreign_connection(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    raw = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match="connection does not belong"):
            ProjectData(str(session.root), db_conn=raw, session=session)
        with pytest.raises(ValueError, match="connection does not belong"):
            TagStore(str(session.root), db_conn=raw, session=session)
    finally:
        raw.close()
        bootstrap.library_service.close()


@pytest.mark.parametrize("close_mode", ["close_session", "close"])
def test_library_service_teardown_invalidates_retained_core_stores(tmp_path, close_mode):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / close_mode)
    project_data = ProjectData(str(session.root), session=session)
    tag_store = TagStore(str(session.root), session=session)
    try:
        if close_mode == "close_session":
            bootstrap.library_service.close_session(session)
        else:
            bootstrap.library_service.close()

        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            project_data.get_notes(str(session.root / "asset.txt"))
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            tag_store.get_all_tags()
    finally:
        bootstrap.library_service.close()
