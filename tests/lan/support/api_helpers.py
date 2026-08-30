"""Shared helpers for LAN API route tests.

Extracted from tests/lan/test_lan_api.py so sibling test modules can import
them without pulling in the monolithic test module (which registers pytest
hooks and carries hundreds of tests).
"""
import os
import sqlite3
from pathlib import Path

from AssetsManager.lan.routes._helpers import PRINCIPAL_REQUEST_KEY

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _write_valid_png(path):
    from PIL import Image

    Image.new("RGB", (2, 2), color="white").save(path, format="PNG")


class _FakeLan:
    def __init__(self, library_root, db_conn, thumbnail_dir):
        self.library_root = library_root
        self.db_conn = db_conn
        self.thumbnail_dir = thumbnail_dir
        self.current_settings = {
            "show_hidden": False,
            "include_types": None,
            "exclude_patterns": [],
            "max_depth": 0,
        }
        self.blur_tags = set()
        self.access_key_hash = None
        self.password_hash = None
        self.share_name = "Test Share"
        self.token_secret = "test-secret"
        self.local_ui_auth_secret = "test-secret"
        self.endpoint_protocol = "http"
        self.ssl_active = False
        self._ssl_cert = None
        self._ssl_key = None
        self._port = 8080
        self.broadcasts = []
        self.performance_recorder = None
        self.session_token = None
        from AssetsManager.lan.ws import WebSocketManager
        self.ws_manager = WebSocketManager()
        from AssetsManager.lan.scanner import DirectoryScanner
        self.scanner = DirectoryScanner(str(library_root), db_conn)
        from AssetsManager.application import (
            AssetService, MetadataService, ProjectService, SearchService,
            TagService, ThumbnailService,
        )
        from AssetsManager.application.collection_service import CollectionService
        from AssetsManager.application.auth_service import AuthService
        from AssetsManager.application.share_service import ShareService
        from AssetsManager.lan.routes._helpers import LanScopedServices
        provider = self.connection_for
        self._auth_service = AuthService(db_conn, self.token_secret)
        self._share_service = ShareService(db_conn, self.token_secret)
        # Session-bound metadata/tag services so Asset*Changed events publish,
        # matching the production LAN composition (bootstrap builds these via
        # for_session; the legacy session-less construction stopped publishing
        # when the unscoped NotesChanged/TagsChanged events were removed).
        from types import SimpleNamespace

        from AssetsManager.application.context import LibraryContext, LibrarySession
        from AssetsManager.core.path_resolver import root_identity
        identity = root_identity(Path(library_root), strict=False)
        context = LibraryContext(
            root=identity.display_path,
            data_dir=identity.display_path / ".data",
            thumb_dir=identity.display_path / ".thumbs",
            db_conn=db_conn,
            tag_store=SimpleNamespace(),
            project_data=SimpleNamespace(),
            root_key=identity.map_key,
        )
        fake_session = LibrarySession.from_context(context)
        # Register the fixture connection as "managed" so session-bound
        # services pass DatabaseManager.require_managed_connection_owner
        # (production binds these services to the DI-managed connection).
        # _make_lan_app's cleanup handler pops this registry entry.
        import threading

        from AssetsManager.core import database as database_module
        state = database_module._ConnectionWriteState(
            threading.RLock(),
            library_root=str(identity.display_path),
            library_root_key=identity.map_key,
        )
        with database_module._connection_locks_guard:
            database_module._connection_locks[id(db_conn)] = state
        tag_service = TagService(session=fake_session)
        # Migration v39 maintainer: the LAN search service reads the FTS
        # fourth source through it and the collection service evaluates the
        # smart-query ``fts`` dimension with it (production wires one shared
        # instance per session in bootstrap).
        from AssetsManager.application.search_index_service import SearchIndexService

        search_index_service = SearchIndexService(lambda: db_conn)
        self.services = LanScopedServices(
            auth_service=self._auth_service,
            metadata_service=MetadataService(
                session=fake_session, search_index_service=search_index_service
            ),
            project_service=ProjectService(connection_provider=provider),
            tag_service=tag_service,
            search_service=SearchService(
                connection_provider=provider,
                search_index_service=search_index_service,
            ),
            thumbnail_service=ThumbnailService(connection_provider=provider),
            asset_service=AssetService(),
            share_service=self._share_service,
            collection_service=CollectionService(
                session=fake_session,
                asset_index_service=_FakeIndexAdapter(db_conn),
                tag_service=tag_service,
                search_index_service=search_index_service,
            ),
        )

    def broadcast(self, event_type, data=None):
        self.broadcasts.append((event_type, data or {}))

    def connection_for(self, library_root=None):
        if library_root is not None and Path(library_root).resolve() != self.library_root.resolve():
            raise ValueError("wrong library root")
        return self.db_conn

    def invalidate_user_cache(self):
        pass


class _FakeIndexAdapter:
    """Forwards smart evaluation to the canonical structured repository query."""

    def __init__(self, conn):
        from AssetsManager.repositories.asset_index_repository import (
            AssetIndexRepository,
        )

        self._repo = AssetIndexRepository(conn)

    def search_structured(self, library_root, **kwargs):
        return self._repo.search_structured(str(library_root), **kwargs)


def _init_lan_schemas(conn):
    from AssetsManager.repositories.auth_repository import AuthRepository
    from AssetsManager.repositories.share_repository import ShareRepository

    AuthRepository(conn).init_tables()
    ShareRepository(conn).init_table()
    # tag_metadata arrives via DB migration v3; fixture databases start from
    # the baseline _SCHEMA, so mirror the migrated shape for tag routes.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tag_metadata ("
        "tag TEXT PRIMARY KEY, "
        "color TEXT DEFAULT '', "
        "icon TEXT DEFAULT '', "
        "category TEXT DEFAULT '', "
        "created_at REAL DEFAULT (strftime('%s','now'))"
        ")"
    )
    # file_meta.rating arrives via DB migration v37; the baseline _SCHEMA
    # lacks the column, so mirror the migrated shape for the rating routes.
    meta_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(file_meta)")
    }
    if "rating" not in meta_columns:
        conn.execute("ALTER TABLE file_meta ADD COLUMN rating INTEGER")
    # asset_collections/asset_collection_members arrive via DB migration v38;
    # mirror the migrated shape for the collection routes.
    from AssetsManager.core.schema_defs import ASSET_COLLECTIONS_SCHEMA

    for statement in ASSET_COLLECTIONS_SCHEMA.split(";"):
        if sql := statement.strip():
            conn.execute(sql)
    # asset_search arrives via DB migration v39 (FTS5 virtual table); mirror
    # the migrated shape for the search routes.
    from AssetsManager.core.schema_defs import ASSET_SEARCH_FTS_SCHEMA

    for statement in ASSET_SEARCH_FTS_SCHEMA.split(";"):
        if sql := statement.strip():
            conn.execute(sql)
    conn.commit()


def _legacy_server(**kwargs):
    """Build a runtime-shaped LAN fixture for low-level route tests."""
    from types import SimpleNamespace

    from AssetsManager.application import (
        AssetService,
        AuthService,
        MetadataService,
        ProjectService,
        RuntimeSharingServices,
        SearchService,
        ShareService,
        TagService,
        ThumbnailService,
    )
    from AssetsManager.core.directory_cache import DirectoryCache
    from AssetsManager.lan.server import _LanServerImpl
    from tests.lan.support.legacy_runtime_adapter import adapt_legacy_runtime

    db_conn = kwargs["db_conn"]

    class Session:
        root = Path(kwargs["library_root"])
        thumb_dir = Path(kwargs["thumbnail_dir"])
        is_closed = False
        event_token = "runtime-test-session"

        def connection_for(self, library_root=None):
            if (
                library_root is not None
                and Path(library_root).resolve() != self.root.resolve()
            ):
                raise ValueError("wrong library")
            return db_conn

    session = Session()
    secret = "runtime-test-secret"
    auth_service = AuthService(db_conn, secret)
    share_service = ShareService(db_conn, secret)
    bundle = SimpleNamespace(
        session=session,
        sharing_services=RuntimeSharingServices(
            token_secret=secret,
            auth_service=auth_service,
            share_service=share_service,
        ),
        auth_service=auth_service,
        metadata_service=MetadataService(connection_provider=session.connection_for),
        project_service=ProjectService(connection_provider=session.connection_for),
        tag_service=TagService(connection_provider=session.connection_for),
        search_service=SearchService(connection_provider=session.connection_for),
        thumbnail_service=ThumbnailService(connection_provider=session.connection_for),
        asset_service=AssetService(directory_cache=DirectoryCache(db_conn)),
        share_service=share_service,
    )

    class EventRouter:
        def subscribe(self, _callback):
            return SimpleNamespace(close=lambda: None)

    runtime = SimpleNamespace(
        session=session,
        services=bundle,
        epoch="runtime-test-epoch",
        revision=0,
        event_router=EventRouter(),
    )
    options = dict(kwargs)
    options.pop("library_root")
    options.pop("thumbnail_dir")
    options.pop("db_conn")
    runtime = adapt_legacy_runtime(runtime)
    return _LanServerImpl(runtime=runtime, **options)


def _make_lan_app(tmp_path, *, authenticated_context_only=False, canonical_context_only=False):
    from aiohttp import web
    from AssetsManager.application.auth_service import AuthService
    from AssetsManager.core import database
    from AssetsManager.lan.api import setup_routes
    from AssetsManager.lan.auth import verify_auth_token
    from AssetsManager.lan.routes._helpers import (
        AUTH_SERVICE_APP_KEY,
        LAN_APP_KEY,
        get_auth_token,
        set_request_principal,
    )
    from AssetsManager.lan.principal import principal_for_request

    library = tmp_path / "library"
    library.mkdir()

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        conn.executescript(database._SCHEMA)
        conn.commit()
        _init_lan_schemas(conn)

        @web.middleware
        async def _test_auth_middleware(request, handler):
            if authenticated_context_only:
                user = {"username": "middleware-user", "role": "user"}
                set_request_principal(request, principal_for_request("user", user=user))
                return await handler(request)
            token = get_auth_token(request)
            if token:
                lan = request.app[LAN_APP_KEY]
                local_ui_secret = getattr(
                    lan, "local_ui_auth_secret", getattr(lan, "token_secret", None)
                )
                if local_ui_secret and verify_auth_token(token, local_ui_secret):
                    set_request_principal(request, principal_for_request("local_ui"))
                else:
                    user = request.app[AUTH_SERVICE_APP_KEY].verify_user_token(token)
                    if user:
                        set_request_principal(request, principal_for_request("user", user=user))
            if request.get(PRINCIPAL_REQUEST_KEY) is None:
                set_request_principal(request, principal_for_request("guest"))
            return await handler(request)

        app = web.Application(middlewares=[_test_auth_middleware])
        app[LAN_APP_KEY] = _FakeLan(library, conn, tmp_path / "thumbs")
        app[AUTH_SERVICE_APP_KEY] = AuthService(conn, "test-secret")
        async def _close_db(_app):
            from AssetsManager.core import database as database_module
            with database_module._connection_locks_guard:
                database_module._connection_locks.pop(id(conn), None)
            conn.close()
        app.on_cleanup.append(_close_db)
        setup_routes(app)
        return app, library, conn
    except Exception:
        conn.close()
        raise


async def _read_body(resp):
    return await resp.read()


async def _make_client(app):
    from aiohttp.test_utils import TestClient, TestServer

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client


def _local_ui_headers(app):
    from AssetsManager.lan.utils import get_auth_headers
    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    return get_auth_headers(
        getattr(
            app[LAN_APP_KEY],
            "local_ui_auth_secret",
            app[LAN_APP_KEY].token_secret,
        )
    )


async def _register_user_token(client, username="alice"):
    resp = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "Test@1234"},
    )
    assert resp.status == 200
    return resp.cookies["lan_token"].value
