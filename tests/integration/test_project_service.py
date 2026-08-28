"""Tests for ProjectService."""

import os
import time

import pytest

from AssetsManager.application.project_service import ProjectDepthConfig, ProjectService


def _write_webp(path, size=(256, 128)):
    from PIL import Image

    Image.new("RGB", size, color="green").save(path, format="WEBP")


def test_list_projects_marks_projects_at_global_depth(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    project = library / "alpha"
    project.mkdir()
    (project / "cover.png").write_bytes(b"png")
    (project / "readme.txt").write_text("notes", encoding="utf-8")

    conn = schema_db
    listing = ProjectService(connection_provider=lambda _root: conn).list_projects(
        library,
        library,
        depth_config=ProjectDepthConfig(global_depth=1),
        db_conn=conn,
    )
    response = listing.to_response()

    assert response["current_path"] == ""
    assert response["parent_path"] == ""
    assert response["project_count"] == 1
    assert response["folder_count"] == 0
    assert response["items"][0]["name"] == "alpha"
    assert response["items"][0]["is_project"] is True
    assert response["items"][0]["thumbnail_path"] == "alpha/cover.png"
    assert "/api/" not in response["items"][0]["thumbnail_path"]
    assert response["items"][0]["file_count"] == 2


def test_list_projects_uses_connection_provider_without_db_conn(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    project = library / "alpha"
    project.mkdir()
    (project / "asset.txt").write_text("asset", encoding="utf-8")

    listing = ProjectService(connection_provider=lambda _root: schema_db).list_projects(
        library, library, depth_config=ProjectDepthConfig(global_depth=1)
    )

    assert listing.items[0].file_count == 1


def test_list_projects_recomputes_file_count_after_directory_mtime_change(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    project = library / "alpha"
    project.mkdir()
    (project / "cover.png").write_bytes(b"png")

    conn = schema_db
    service = ProjectService(connection_provider=lambda _root: conn)
    listing = service.list_projects(
        library,
        library,
        depth_config=ProjectDepthConfig(global_depth=1),
        db_conn=conn,
    )
    assert listing.items[0].file_count == 1
    stamped = conn.execute(
        "SELECT cached_file_count, cached_file_count_mtime FROM file_meta WHERE file_path=?",
        (str(project.resolve()),),
    ).fetchone()
    assert stamped is not None
    assert stamped[0] == 1
    assert stamped[1] is not None

    # A file arrives through a path that does not refresh any index, and the
    # directory mtime moves past the stamp recorded above.
    (project / "extra.txt").write_text("extra", encoding="utf-8")
    future = time.time() + 120
    os.utime(project, (future, future))

    # The cached count must not be served again: the stale stamp forces a
    # recompute in both the batch warm pass and the per-entry read.
    listing = service.list_projects(
        library,
        library,
        depth_config=ProjectDepthConfig(global_depth=1),
        db_conn=conn,
    )
    assert listing.items[0].file_count == 2
    refreshed = conn.execute(
        "SELECT cached_file_count, cached_file_count_mtime FROM file_meta WHERE file_path=?",
        (str(project.resolve()),),
    ).fetchone()
    assert refreshed[0] == 2
    assert refreshed[1] == pytest.approx(future, abs=1e-6)


def test_list_projects_applies_branch_depth_and_search(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    (library / "folder").mkdir()
    hero = library / "hero"
    hero.mkdir()
    villain = library / "villain"
    villain.mkdir()

    conn = schema_db
    listing = ProjectService(connection_provider=lambda _root: conn).list_projects(
        library,
        library,
        search="hero",
        depth_config=ProjectDepthConfig(global_depth=2, branch_depths={"hero": 1}),
        db_conn=conn,
    )
    response = listing.to_response()

    assert response["total_count"] == 1
    assert response["project_count"] == 1
    assert response["folder_count"] == 0
    assert response["items"][0]["name"] == "hero"
    assert response["items"][0]["is_project"] is True
    assert response["depth_config"] == {
        "global": 2,
        "branches": {"hero": 1},
        "current_depth": 0,
    }


def test_list_projects_sorts_folders_before_projects(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    (library / "z_folder").mkdir()
    (library / "a_project").mkdir()

    conn = schema_db
    listing = ProjectService(connection_provider=lambda _root: conn).list_projects(
        library,
        library,
        sort_by="name",
        order="asc",
        depth_config=ProjectDepthConfig(global_depth=2, branch_depths={"a_project": 1}),
        db_conn=conn,
    )

    assert [item.name for item in listing.items] == ["z_folder", "a_project"]
    assert [item.is_project for item in listing.items] == [False, True]


def test_get_project_detail_returns_relative_resource_references(tmp_path, schema_db):
    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    (project / "cover.png").write_bytes(b"png")
    (project / "readme.txt").write_text("readme", encoding="utf-8")
    (project / ".hidden.txt").write_text("hidden", encoding="utf-8")

    conn = schema_db
    detail = ProjectService(connection_provider=lambda _root: conn).get_project_detail(
        library, project, rel_path="alpha", db_conn=conn,
    ).to_response()

    assert detail["name"] == "alpha"
    assert detail["path"] == "alpha"
    assert detail["file_count"] == 2
    assert detail["thumbnail_path"] == "alpha/cover.png"
    assert "download_url" not in detail
    assert [file["name"] for file in detail["files"]] == ["cover.png", "readme.txt"]
    assert detail["images"] == [{"name": "cover.png", "path": "alpha/cover.png"}]


def test_get_project_detail_includes_tags(tmp_path, schema_db):
    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    asset = project / "asset.txt"
    asset.write_text("asset", encoding="utf-8")

    conn = schema_db
    conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?, ?)", (str(asset.resolve()), "hero"))
    conn.commit()

    detail = ProjectService(connection_provider=lambda _root: conn).get_project_detail(
        library, project, rel_path="alpha", db_conn=conn,
    ).to_response()

    assert detail["tags"] == ["hero"]


def test_get_project_detail_uses_connection_provider_without_db_conn(tmp_path, schema_db):
    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    asset = project / "asset.txt"
    asset.write_text("asset", encoding="utf-8")

    conn = schema_db
    conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?, ?)", (str(asset.resolve()), "scoped"))
    conn.execute("INSERT INTO file_meta (file_path, notes) VALUES (?, ?)", (str(project.resolve()), "provider notes"))
    conn.commit()

    service = ProjectService(connection_provider=lambda _root: conn)
    detail = service.get_project_detail(library, project, rel_path="alpha").to_response()

    assert detail["tags"] == ["scoped"]
    assert detail["notes"] == "provider notes"


def test_get_home_uses_connection_provider_without_db_conn(tmp_path, schema_db):
    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    schema_db.execute(
        "INSERT INTO library_stats (library_path, total_size) VALUES (?, ?)",
        (str(library.resolve()), 123),
    )
    schema_db.commit()

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1)
    )

    assert home.total_projects == 1
    assert home.total_size == 123


def test_build_tree_returns_nodes_with_depth_config(tmp_path, memory_db):
    library = tmp_path / "library"
    library.mkdir()
    (library / "a").mkdir()
    (library / "a" / "b").mkdir()
    (library / "a" / "b" / "c").mkdir()

    tree = ProjectService(connection_provider=lambda _root: memory_db).build_tree(
        library, depth_config=ProjectDepthConfig(global_depth=2, branch_depths={"a": 3}),
    ).to_response()

    assert tree["depth_config"] == {"global": 2, "branches": {"a": 3}}
    assert len(tree["tree"]) == 1
    a_node = tree["tree"][0]
    assert a_node["name"] == "a"
    assert a_node["path"] == "a"
    assert a_node["is_leaf"] is False
    assert len(a_node["children"]) == 1
    b_node = a_node["children"][0]
    assert b_node["name"] == "b"
    assert b_node["path"] == "a/b"
    assert b_node["is_leaf"] is False
    c_node = b_node["children"][0]
    assert c_node["name"] == "c"
    assert c_node["path"] == "a/b/c"
    assert c_node["is_leaf"] is True
    assert c_node["children"] == []


def test_build_tree_marks_leaves_at_default_depth(tmp_path, memory_db):
    library = tmp_path / "library"
    library.mkdir()
    (library / "x").mkdir()
    (library / "x" / "y").mkdir()

    tree = ProjectService(connection_provider=lambda _root: memory_db).build_tree(
        library, depth_config=ProjectDepthConfig(global_depth=1),
    ).to_response()

    x_node = tree["tree"][0]
    assert x_node["name"] == "x"
    assert x_node["is_leaf"] is True
    assert x_node["children"] == []


def test_get_home_returns_recent_projects_and_stats(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    (library / "old_project").mkdir()
    (library / "new_project").mkdir()

    conn = schema_db
    conn.execute(
        "INSERT INTO library_stats (library_path, total_size) VALUES (?, ?)",
        (str(library.resolve()), 1024),
    )
    conn.commit()

    home = ProjectService(connection_provider=lambda _root: conn).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=conn,
    ).to_response()

    assert home["stats"]["total_projects"] == 2
    assert home["stats"]["total_size"] == 1024
    assert home["stats"]["total_size_fmt"] == "1.0 KB"
    assert len(home["recent_projects"]) == 2


def test_get_home_uses_directory_cache_preview_path(tmp_path, schema_db):
    from AssetsManager.core.directory_cache import DirectoryCache

    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    preview = project / "cover.png"
    preview.write_bytes(b"png")

    DirectoryCache(schema_db).set(
        str(project.resolve()),
        item_count=1,
        preview_path=str(preview.resolve()),
        mtime=project.stat().st_mtime,
    )

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert home["recent_projects"] == [{
        "name": "alpha",
        "path": "alpha",
        "mtime": project.stat().st_mtime,
        "thumbnail_path": "alpha/cover.png",
    }]


def test_get_home_rejects_directory_cache_preview_from_another_project(
    tmp_path, schema_db,
):
    from AssetsManager.core.directory_cache import DirectoryCache

    library = tmp_path / "library"
    alpha = library / "alpha"
    beta = library / "beta"
    alpha.mkdir(parents=True)
    beta.mkdir()
    beta_preview = beta / "cover.png"
    beta_preview.write_bytes(b"png")

    cache = DirectoryCache(schema_db)
    cache.set(
        str(alpha.resolve()),
        item_count=1,
        preview_path=str(beta_preview.resolve()),
        mtime=alpha.stat().st_mtime,
    )
    cache.set(
        str(beta.resolve()),
        item_count=1,
        preview_path=str(beta_preview.resolve()),
        mtime=beta.stat().st_mtime,
    )

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    projects = {project["path"]: project for project in home["recent_projects"]}
    assert "thumbnail_path" not in projects["alpha"]
    assert projects["beta"]["thumbnail_path"] == "beta/cover.png"


def test_get_home_uses_baked_thumbnail_cache_when_directory_cache_has_no_preview(
    tmp_path, schema_db,
):
    from AssetsManager.application.thumbnail_service import thumbnail_cache_key
    from AssetsManager.core.path_resolver import thumb_dir

    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    source = project / "cover.png"
    source.write_bytes(b"png")

    cache_key = thumbnail_cache_key(source)
    baked = thumb_dir(str(library)) / f"{cache_key}.webp"
    baked.parent.mkdir(parents=True)
    _write_webp(baked)
    schema_db.execute(
        """
        INSERT INTO thumbnail_cache
        (cache_key, source_path, source_mtime, source_size, baked_size, cache_size)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            cache_key,
            str(source.resolve()),
            source.stat().st_mtime,
            source.stat().st_size,
            256,
            baked.stat().st_size,
        ),
    )
    schema_db.commit()

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert home["recent_projects"][0]["thumbnail_path"] == "alpha/cover.png"


def test_get_home_ignores_baked_thumbnail_source_outside_library_via_symlink(
    tmp_path, schema_db,
):
    import os
    from AssetsManager.application.thumbnail_service import thumbnail_cache_key
    from AssetsManager.core.path_resolver import thumb_dir

    library = tmp_path / "library"
    external = tmp_path / "external"
    library.mkdir()
    external.mkdir()
    project = library / "linked"
    try:
        project.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        import pytest
        pytest.skip("directory symlinks are unavailable on this platform")

    source = external / "cover.png"
    source.write_bytes(b"png")
    cache_key = thumbnail_cache_key(source)
    baked = thumb_dir(str(library)) / f"{cache_key}.webp"
    baked.parent.mkdir(parents=True)
    _write_webp(baked)
    schema_db.execute(
        """
        INSERT INTO thumbnail_cache
        (cache_key, source_path, source_mtime, source_size, baked_size, cache_size)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            cache_key,
            str(source.resolve()),
            source.stat().st_mtime,
            source.stat().st_size,
            256,
            baked.stat().st_size,
        ),
    )
    schema_db.commit()

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert os.path.samefile(project, external)
    # Product contract: entries behind links/reparse points are never admitted
    # as projects (fail-closed discovery), so the symlinked project is not
    # discovered at all and its outside-library baked thumbnail can never
    # surface. (The old assertion indexed recent_projects[0], which only
    # "passed" on Windows because unprivileged symlink creation skipped the
    # test there before discovery ever ran.)
    assert home["recent_projects"] == []
    assert home["preview_pool"] == []


def _insert_webp_thumbnail_row(
    conn,
    *,
    key,
    source,
    baked,
    baked_size=256,
    render_profile=None,
    source_size=None,
    source_mtime_ns=None,
):
    stat = source.stat()
    conn.execute(
        """
        INSERT INTO thumbnail_cache
        (cache_key, source_path, source_mtime, source_size, baked_size,
         cache_size, source_mtime_ns, artifact_kind, render_profile)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'webp', ?)
        """,
        (
            key,
            str(source.resolve()),
            stat.st_mtime,
            stat.st_size if source_size is None else source_size,
            baked_size,
            baked.stat().st_size,
            stat.st_mtime_ns if source_mtime_ns is None else source_mtime_ns,
            render_profile,
        ),
    )
    conn.commit()


def test_get_home_ignores_profile_mismatch_but_keeps_valid_legacy_row(
    tmp_path, schema_db,
):
    from AssetsManager.application.thumbnail_service import thumbnail_cache_key
    from AssetsManager.core.path_resolver import thumb_dir

    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    source = project / "cover.png"
    source.write_bytes(b"png")
    baked_root = thumb_dir(str(library))
    baked_root.mkdir(parents=True)
    legacy_key = thumbnail_cache_key(source)
    legacy_baked = baked_root / f"{legacy_key}.webp"
    _write_webp(legacy_baked)
    _insert_webp_thumbnail_row(
        schema_db, key=legacy_key, source=source, baked=legacy_baked,
    )
    bad_key = "bad-profile-key"
    bad_baked = baked_root / f"{bad_key}.webp"
    bad_baked.write_bytes(b"bad")
    _insert_webp_thumbnail_row(
        schema_db,
        key=bad_key,
        source=source,
        baked=bad_baked,
        baked_size=512,
        render_profile="desktop-webp-256-v1",
    )

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert home["recent_projects"][0]["thumbnail_path"] == "alpha/cover.png"


def test_get_home_rejects_unknown_profile_and_stale_source_identity(tmp_path, schema_db):
    from AssetsManager.application.thumbnail_service import thumbnail_cache_key
    from AssetsManager.core.path_resolver import thumb_dir

    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    source = project / "cover.png"
    source.write_bytes(b"png")
    baked_root = thumb_dir(str(library))
    baked_root.mkdir(parents=True)

    unknown_key = "unknown-profile-key"
    unknown_baked = baked_root / f"{unknown_key}.webp"
    unknown_baked.write_bytes(b"unknown")
    _insert_webp_thumbnail_row(
        schema_db,
        key=unknown_key,
        source=source,
        baked=unknown_baked,
        baked_size=512,
        render_profile="desktop-webp-unknown-v1",
    )
    stale_key = thumbnail_cache_key(source)
    stale_baked = baked_root / f"{stale_key}.webp"
    stale_baked.write_bytes(b"stale")
    _insert_webp_thumbnail_row(
        schema_db,
        key=stale_key,
        source=source,
        baked=stale_baked,
        source_size=source.stat().st_size + 1,
    )

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert "thumbnail_path" not in home["recent_projects"][0]


def test_get_home_ignores_nested_thumbnail_cache_key(tmp_path, schema_db):
    from AssetsManager.core.path_resolver import thumb_dir

    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    source = project / "cover.png"
    source.write_bytes(b"png")
    baked_root = thumb_dir(str(library))
    nested = baked_root / "nested"
    nested.mkdir(parents=True)
    nested_baked = nested / "key.webp"
    nested_baked.write_bytes(b"nested")
    _insert_webp_thumbnail_row(
        schema_db,
        key="nested/key",
        source=source,
        baked=nested_baked,
    )

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert "thumbnail_path" not in home["recent_projects"][0]


def test_get_home_skips_malformed_or_undersized_baked_webp(tmp_path, schema_db):
    from AssetsManager.application.thumbnail_service import thumbnail_cache_key
    from AssetsManager.core.path_resolver import thumb_dir

    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    source = project / "cover.png"
    source.write_bytes(b"png")
    baked_root = thumb_dir(str(library))
    baked_root.mkdir(parents=True)

    malformed_key = thumbnail_cache_key(source)
    malformed = baked_root / f"{malformed_key}.webp"
    malformed.write_bytes(b"not-webp")
    _insert_webp_thumbnail_row(
        schema_db, key=malformed_key, source=source, baked=malformed,
    )

    undersized_source = project / "small.png"
    undersized_source.write_bytes(b"small")
    undersized_key = thumbnail_cache_key(undersized_source)
    undersized = baked_root / f"{undersized_key}.webp"
    _write_webp(undersized, (128, 64))
    _insert_webp_thumbnail_row(
        schema_db,
        key=undersized_key,
        source=undersized_source,
        baked=undersized,
        render_profile="desktop-webp-256-v1",
    )

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert "thumbnail_path" not in home["recent_projects"][0]
    assert malformed.exists()
    assert undersized.exists()


def test_get_home_selects_valid_lower_profile_when_higher_profile_is_malformed(
    tmp_path, schema_db,
):
    from AssetsManager.application.thumbnail_service import profiled_thumbnail_cache_key_v3
    from AssetsManager.core.path_resolver import thumb_dir

    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    source = project / "cover.png"
    source.write_bytes(b"png")
    baked_root = thumb_dir(str(library))
    baked_root.mkdir(parents=True)

    low_key = profiled_thumbnail_cache_key_v3(source, "desktop-webp-256-v1")
    low = baked_root / f"{low_key}.webp"
    _write_webp(low, (256, 128))
    _insert_webp_thumbnail_row(
        schema_db,
        key=low_key,
        source=source,
        baked=low,
        render_profile="desktop-webp-256-v1",
    )
    high_key = profiled_thumbnail_cache_key_v3(source, "desktop-webp-512-v1")
    high = baked_root / f"{high_key}.webp"
    high.write_bytes(b"malformed")
    _insert_webp_thumbnail_row(
        schema_db,
        key=high_key,
        source=source,
        baked=high,
        baked_size=512,
        render_profile="desktop-webp-512-v1",
    )

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert home["recent_projects"][0]["thumbnail_path"] == "alpha/cover.png"


def test_get_home_skips_artifact_when_shared_admission_rejects(
    tmp_path, schema_db, monkeypatch,
):
    from AssetsManager.application.thumbnail_service import thumbnail_cache_key
    from AssetsManager.core.path_resolver import thumb_dir

    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    source = project / "cover.png"
    source.write_bytes(b"png")
    baked_root = thumb_dir(str(library))
    baked_root.mkdir(parents=True)
    key = thumbnail_cache_key(source)
    baked = baked_root / f"{key}.webp"
    _write_webp(baked)
    _insert_webp_thumbnail_row(
        schema_db, key=key, source=source, baked=baked,
    )
    monkeypatch.setattr(
        "AssetsManager.application.project_service.admit_thumbnail_cache_artifact",
        lambda *_args, **_kwargs: None,
    )

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert "thumbnail_path" not in home["recent_projects"][0]
    assert baked.exists()


def test_get_home_excludes_jpg_thumbnail_rows(tmp_path, schema_db):
    from AssetsManager.application.thumbnail_service import thumbnail_cache_key
    from AssetsManager.core.path_resolver import thumb_dir

    library = tmp_path / "library"
    project = library / "alpha"
    project.mkdir(parents=True)
    source = project / "clip.mp4"
    source.write_bytes(b"video")
    baked_root = thumb_dir(str(library))
    baked_root.mkdir(parents=True)
    key = thumbnail_cache_key(source)
    baked = baked_root / f"{key}.jpg"
    baked.write_bytes(b"jpg")
    stat = source.stat()
    schema_db.execute(
        """
        INSERT INTO thumbnail_cache
        (cache_key, source_path, source_mtime, source_size, baked_size,
         cache_size, source_mtime_ns, artifact_kind)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'jpg')
        """,
        (key, str(source.resolve()), stat.st_mtime, stat.st_size, 512,
         baked.stat().st_size, stat.st_mtime_ns),
    )
    schema_db.commit()

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert "thumbnail_path" not in home["recent_projects"][0]


def test_get_home_baked_thumbnail_matching_ignores_unrelated_cache_rows(
    tmp_path, schema_db,
):
    from AssetsManager.application.thumbnail_service import thumbnail_cache_key
    from AssetsManager.core.path_resolver import thumb_dir

    library = tmp_path / "library"
    project = library / "alpha"
    unrelated = tmp_path / "unrelated"
    project.mkdir(parents=True)
    unrelated.mkdir()
    source = project / "cover.png"
    source.write_bytes(b"png")

    rows = []
    for index in range(100):
        other = unrelated / f"other-{index}.png"
        other.write_bytes(b"png")
        key = thumbnail_cache_key(other)
        baked = thumb_dir(str(library)) / f"{key}.webp"
        baked.parent.mkdir(parents=True, exist_ok=True)
        _write_webp(baked)
        rows.append((key, str(other.resolve()), other.stat().st_mtime, other.stat().st_size, 256, baked.stat().st_size))

    key = thumbnail_cache_key(source)
    baked = thumb_dir(str(library)) / f"{key}.webp"
    _write_webp(baked)
    rows.append((key, str(source.resolve()), source.stat().st_mtime, source.stat().st_size, 256, baked.stat().st_size))
    schema_db.executemany(
        """
        INSERT INTO thumbnail_cache
        (cache_key, source_path, source_mtime, source_size, baked_size, cache_size)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    schema_db.commit()

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    projects = {item["path"]: item for item in home["recent_projects"]}
    assert projects["alpha"]["thumbnail_path"] == "alpha/cover.png"


def test_get_home_baked_thumbnail_matching_does_not_scan_projects_per_cache_row(
    tmp_path, schema_db, monkeypatch,
):
    from pathlib import Path
    from AssetsManager.application.thumbnail_service import thumbnail_cache_key
    from AssetsManager.core.path_resolver import thumb_dir

    library = tmp_path / "library"
    library.mkdir()
    for index in range(100):
        (library / f"project-{index}").mkdir()

    rows = []
    for index in range(100):
        source = library / f"project-{index}" / "cover.png"
        source.write_bytes(b"png")
        key = thumbnail_cache_key(source)
        baked = thumb_dir(str(library)) / f"{key}.webp"
        baked.parent.mkdir(parents=True, exist_ok=True)
        _write_webp(baked)
        rows.append((key, str(source.resolve()), source.stat().st_mtime, source.stat().st_size, 256, baked.stat().st_size))
    schema_db.executemany(
        """
        INSERT INTO thumbnail_cache
        (cache_key, source_path, source_mtime, source_size, baked_size, cache_size)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    schema_db.commit()

    real_relative_to = Path.relative_to
    relative_to_calls = {"count": 0}

    def counting_relative_to(self, *other):
        relative_to_calls["count"] += 1
        return real_relative_to(self, *other)

    monkeypatch.setattr(Path, "relative_to", counting_relative_to)
    ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    )

    assert relative_to_calls["count"] < 1000


def test_get_home_ignores_stale_or_missing_directory_cache_preview(tmp_path, schema_db):
    from AssetsManager.core.directory_cache import DirectoryCache

    library = tmp_path / "library"
    stale = library / "stale"
    missing = library / "missing"
    stale.mkdir(parents=True)
    missing.mkdir()
    stale_preview = stale / "cover.png"
    stale_preview.write_bytes(b"png")

    cache = DirectoryCache(schema_db)
    cache.set(
        str(stale.resolve()),
        item_count=1,
        preview_path=str(stale_preview.resolve()),
        mtime=stale.stat().st_mtime - 1,
    )
    cache.set(
        str(missing.resolve()),
        item_count=1,
        preview_path=str((missing / "cover.png").resolve()),
        mtime=missing.stat().st_mtime,
    )

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert all("thumbnail_path" not in project for project in home["recent_projects"])


def test_get_home_batches_directory_cache_reads(tmp_path, schema_db, monkeypatch):
    from AssetsManager.core.directory_cache import DirectoryCache as RealDirectoryCache

    library = tmp_path / "library"
    first = library / "first"
    second = library / "second"
    first.mkdir(parents=True)
    second.mkdir()
    calls = {"get": 0, "get_batch": 0}

    class SpyDirectoryCache:
        def __init__(self, conn):
            self._real = RealDirectoryCache(conn)

        def get(self, *args, **kwargs):
            calls["get"] += 1
            raise AssertionError("Home must batch directory cache reads")

        def get_batch(self, paths):
            calls["get_batch"] += 1
            return self._real.get_batch(paths)

    monkeypatch.setattr(
        "AssetsManager.application.project_service.DirectoryCache",
        SpyDirectoryCache,
    )

    ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    )

    assert calls["get_batch"] == 1
    assert calls["get"] == 0


def test_get_home_limits_recent_projects_to_20(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    for i in range(25):
        (library / f"project_{i:02d}").mkdir()

    conn = schema_db
    home = ProjectService(connection_provider=lambda _root: conn).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=conn,
    ).to_response()

    assert home["stats"]["total_projects"] == 25
    assert len(home["recent_projects"]) == 20


def test_get_home_preview_pool_covers_all_valid_cached_thumbnails(tmp_path, schema_db):
    import os

    from AssetsManager.application.thumbnail_service import thumbnail_cache_key
    from AssetsManager.core.directory_cache import DirectoryCache
    from AssetsManager.core.path_resolver import thumb_dir

    library = tmp_path / "library"
    library.mkdir()
    projects = []
    for index in range(25):
        project = library / f"project_{index:02d}"
        project.mkdir()
        os.utime(project, (index + 1, index + 1))
        projects.append(project)

    directory_preview = projects[0] / "directory-cover.png"
    directory_preview.write_bytes(b"png")
    DirectoryCache(schema_db).set(
        str(projects[0].resolve()),
        item_count=1,
        preview_path=str(directory_preview.resolve()),
        mtime=projects[0].stat().st_mtime,
    )

    baked_source = projects[1] / "baked-cover.png"
    baked_source.write_bytes(b"png")
    baked_key = thumbnail_cache_key(baked_source)
    baked_preview = thumb_dir(str(library)) / f"{baked_key}.webp"
    baked_preview.parent.mkdir(parents=True)
    _write_webp(baked_preview)

    stale_source = projects[2] / "stale-cover.png"
    stale_source.write_bytes(b"png")
    stale_key = thumbnail_cache_key(stale_source)
    stale_preview = thumb_dir(str(library)) / f"{stale_key}.webp"
    _write_webp(stale_preview)
    schema_db.executemany(
        """
        INSERT INTO thumbnail_cache
        (cache_key, source_path, source_mtime, source_size, baked_size, cache_size)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                baked_key,
                str(baked_source.resolve()),
                baked_source.stat().st_mtime,
                baked_source.stat().st_size,
                256,
                baked_preview.stat().st_size,
            ),
            (
                stale_key,
                str(stale_source.resolve()),
                stale_source.stat().st_mtime - 1,
                stale_source.stat().st_size,
                256,
                stale_preview.stat().st_size,
            ),
        ],
    )
    schema_db.commit()

    home = ProjectService(connection_provider=lambda _root: schema_db).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=schema_db,
    ).to_response()

    assert len(home["recent_projects"]) == 20
    preview_pool = {item["path"]: item for item in home["preview_pool"]}
    assert preview_pool["project_00"]["thumbnail_path"] == \
        "project_00/directory-cover.png"
    assert preview_pool["project_01"]["thumbnail_path"] == \
        "project_01/baked-cover.png"
    assert "project_02" not in preview_pool


def test_get_home_returns_empty_tags_without_error(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()

    conn = schema_db
    home = ProjectService(connection_provider=lambda _root: conn).get_home(
        library, depth_config=ProjectDepthConfig(global_depth=1), db_conn=conn,
    ).to_response()

    assert home["popular_tags"] == []
    assert home["stats"]["total_projects"] == 0


def test_get_project_detail_file_count_excludes_directories(tmp_path, schema_db):
    library = tmp_path / "library"
    project = library / "project"
    project.mkdir(parents=True)
    (project / "file1.txt").write_text("a", encoding="utf-8")
    (project / "file2.txt").write_text("b", encoding="utf-8")
    (project / "subdir").mkdir()

    conn = schema_db
    detail = ProjectService(connection_provider=lambda _root: conn).get_project_detail(
        library, project, rel_path="project", db_conn=conn,
    ).to_response()

    assert detail["file_count"] == 2


def test_list_projects_pagination(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    for i in range(10):
        (library / f"project_{i:02d}").mkdir()

    conn = schema_db

    # First page
    listing = ProjectService(connection_provider=lambda _root: conn).list_projects(
        library, library,
        depth_config=ProjectDepthConfig(global_depth=1),
        db_conn=conn, offset=0, limit=3,
    ).to_response()
    assert listing["total_count"] == 10
    assert len(listing["items"]) == 3
    assert listing["offset"] == 0
    assert listing["limit"] == 3
    assert listing["has_more"] is True

    # Second page
    listing = ProjectService(connection_provider=lambda _root: conn).list_projects(
        library, library,
        depth_config=ProjectDepthConfig(global_depth=1),
        db_conn=conn, offset=3, limit=3,
    ).to_response()
    assert listing["total_count"] == 10
    assert len(listing["items"]) == 3
    assert listing["offset"] == 3
    assert listing["has_more"] is True

    # Last page
    listing = ProjectService(connection_provider=lambda _root: conn).list_projects(
        library, library,
        depth_config=ProjectDepthConfig(global_depth=1),
        db_conn=conn, offset=9, limit=3,
    ).to_response()
    assert listing["total_count"] == 10
    assert len(listing["items"]) == 1
    assert listing["offset"] == 9
    assert listing["has_more"] is False

    # No pagination
    listing = ProjectService(connection_provider=lambda _root: conn).list_projects(
        library, library,
        depth_config=ProjectDepthConfig(global_depth=1),
        db_conn=conn,
    ).to_response()
    assert listing["total_count"] == 10
    assert len(listing["items"]) == 10
    assert listing["offset"] == 0
    assert listing["limit"] == 0
    assert listing["has_more"] is False


def test_project_service_accepts_managed_same_root_connection(tmp_path):
    from AssetsManager.core.database import DatabaseManager

    library = tmp_path / "library"
    library.mkdir()
    manager = DatabaseManager()
    try:
        conn = manager.connection_for(library)
        listing = ProjectService(connection_provider=lambda _root: conn).list_projects(
            library, library
        )

        assert listing.items == ()
    finally:
        manager.close()


@pytest.mark.parametrize("operation", ["list_projects", "get_home", "get_project_detail"])
def test_project_service_rejects_managed_foreign_root_at_public_db_boundary(
    tmp_path, operation
):
    from AssetsManager.core.database import DatabaseManager

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    project = root_a / "project"
    project.mkdir()
    manager = DatabaseManager()
    try:
        foreign_conn = manager.connection_for(root_b)
        service = ProjectService(connection_provider=lambda _root: foreign_conn)

        with pytest.raises(ValueError, match="different library root"):
            if operation == "list_projects":
                service.list_projects(root_a, root_a)
            elif operation == "get_home":
                service.get_home(root_a, depth_config=ProjectDepthConfig(global_depth=1))
            else:
                service.get_project_detail(root_a, project, rel_path="project")
    finally:
        manager.close()


def test_session_bound_project_service_rejects_unmanaged_explicit_connection(tmp_path):
    import sqlite3

    from AssetsManager.application.library_service import LibraryService

    library = tmp_path / "library"
    library.mkdir()
    library_service = LibraryService()
    session = library_service.open_session(library)
    unmanaged = sqlite3.connect(":memory:")
    try:
        service = ProjectService(
            connection_provider=session.connection_for, session=session
        )
        with pytest.raises(ValueError, match="does not belong to the bound LibrarySession"):
            service.get_home(
                library,
                depth_config=ProjectDepthConfig(global_depth=1),
                db_conn=unmanaged,
            )
    finally:
        unmanaged.close()
        library_service.close_session(session)


def test_project_service_explicit_unmanaged_connection_overrides_provider(
    tmp_path, schema_db
):
    library = tmp_path / "library"
    library.mkdir()

    def failing_provider(_root):
        raise AssertionError("provider must not be called")

    listing = ProjectService(connection_provider=failing_provider).list_projects(
        library, library, db_conn=schema_db
    )

    assert listing.items == ()


def test_project_service_closed_session_error_is_not_converted_to_empty_tags(tmp_path):
    from AssetsManager.application.library_service import LibraryService

    library = tmp_path / "library"
    library.mkdir()
    (library / "project").mkdir()
    library_service = LibraryService()
    session = library_service.open_session(library)
    service = ProjectService(connection_provider=session.connection_for, session=session)
    session.close()

    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        service.list_projects(
            library, library, depth_config=ProjectDepthConfig(global_depth=1)
        )


def test_project_service_tag_ownership_error_is_not_converted_to_empty_tags(tmp_path, schema_db):
    library = tmp_path / "library"
    project = library / "project"
    project.mkdir(parents=True)

    service = ProjectService(connection_provider=lambda _root: schema_db)

    def raise_ownership_error(*args, **kwargs):
        raise ValueError("path belongs to a different library root")

    service._tag_svc.get_tags_for_tree = raise_ownership_error

    with pytest.raises(ValueError, match="different library root"):
        service.get_project_detail(library, project, rel_path="project", db_conn=schema_db)


def test_list_projects_does_not_treat_closed_connection_as_empty_cache(tmp_path):
    import sqlite3

    library = tmp_path / "library"
    library.mkdir()
    (library / "project").mkdir()
    conn = sqlite3.connect(":memory:")
    conn.close()

    with pytest.raises(sqlite3.ProgrammingError):
        ProjectService(connection_provider=lambda _root: conn).list_projects(
            library,
            library,
            depth_config=ProjectDepthConfig(global_depth=1),
            db_conn=conn,
        )


def test_project_aggregate_helpers_do_not_hide_closed_connection_errors(tmp_path):
    import sqlite3
    from pathlib import Path

    service = object.__new__(ProjectService)
    closed = sqlite3.connect(":memory:")
    closed.close()
    root = Path(tmp_path)
    target = root / "project"
    target.mkdir()

    with pytest.raises(sqlite3.ProgrammingError):
        service._file_count(root, target, closed)

    class RaisingMetadataService:
        def get_dir_size(self, *args, **kwargs):
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")

        def get_notes(self, *args, **kwargs):
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")

        def get_metadata(self, *args, **kwargs):
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")

    class RaisingTagService:
        def get_tags_for_tree(self, *args, **kwargs):
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")

        def list_tags(self, *args, **kwargs):
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")

    service._metadata_svc = RaisingMetadataService()
    service._tag_svc = RaisingTagService()

    with pytest.raises(sqlite3.ProgrammingError):
        service._dir_size(root, target)
    with pytest.raises(sqlite3.ProgrammingError):
        service._tags(root, target, closed)
    with pytest.raises(sqlite3.ProgrammingError):
        service._notes(root, target)
    with pytest.raises(sqlite3.ProgrammingError):
        service._notes_and_urls(root, target)
    with pytest.raises(sqlite3.ProgrammingError):
        service._popular_tags(root, closed)


def test_list_projects_rejects_target_outside_library_root(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError):
        ProjectService(connection_provider=lambda _root: schema_db).list_projects(
            library, outside, db_conn=schema_db
        )


def test_get_project_detail_rejects_target_outside_library_root(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError):
        ProjectService(connection_provider=lambda _root: schema_db).get_project_detail(
            library, outside, rel_path="", db_conn=schema_db
        )


def test_depth_config_from_dict_clamps_global_depth_bounds():
    assert ProjectDepthConfig.from_dict({"depth": 999}).global_depth == 32
    assert ProjectDepthConfig.from_dict({"depth": 0}).global_depth == 1
    assert ProjectDepthConfig.from_dict({"depth": -5}).global_depth == 1
    assert ProjectDepthConfig.from_dict({"depth": 7}).global_depth == 7
    assert ProjectDepthConfig.from_dict({"depth": "abc"}).global_depth == 2
    assert ProjectDepthConfig.from_dict(None).global_depth == 2
    assert ProjectDepthConfig.from_dict({}).global_depth == 2


def test_depth_config_from_dict_clamps_branch_depths():
    config = ProjectDepthConfig.from_dict(
        {
            "depth": 2,
            "branch_depths": {"alpha": 999, "beta": 0, "gamma": "x", "delta": 5},
        }
    )
    assert config.branches == {"alpha": 32, "beta": 1, "gamma": 2, "delta": 5}


def test_depth_config_direct_construction_is_bounded():
    assert ProjectDepthConfig(global_depth=999).global_depth == 32
    assert ProjectDepthConfig(global_depth=-3).global_depth == 1
    assert ProjectDepthConfig(global_depth=2, branch_depths={"a": 100}).branches == {"a": 32}
