"""Project service containment regressions for link/reparse entries."""

import pytest

from AssetsManager.application.project_service import ProjectDepthConfig, ProjectService


def _service(conn):
    return ProjectService(connection_provider=lambda _root: conn)


def test_project_service_preserves_ordinary_project_paths(tmp_path, schema_db):
    library = tmp_path / "library"
    project = library / "inside"
    library.mkdir()
    project.mkdir()
    (project / "asset.txt").write_text("asset", encoding="utf-8")
    (project / "cover.png").write_bytes(b"png")

    service = _service(schema_db)
    config = ProjectDepthConfig(global_depth=1)

    listing = service.list_projects(library, library, depth_config=config, db_conn=schema_db).to_response()
    detail = service.get_project_detail(
        library, project, rel_path="inside", db_conn=schema_db
    ).to_response()
    tree = service.build_tree(library, depth_config=config).to_response()
    home = service.get_home(library, depth_config=config, db_conn=schema_db).to_response()

    assert listing["items"][0]["path"] == "inside"
    assert listing["items"][0]["file_count"] == 2
    assert listing["items"][0]["thumbnail_path"] == "inside/cover.png"
    assert detail["files"] == [
        {
            "name": "asset.txt",
            "size": 5,
            "size_fmt": "5.0 B",
            "extension": ".txt",
            "category": "documents",
        },
        {
            "name": "cover.png",
            "size": 3,
            "size_fmt": "3.0 B",
            "extension": ".png",
            "category": "images",
        },
    ]
    assert detail["images"] == [{"name": "cover.png", "path": "inside/cover.png"}]
    assert tree["tree"] == [
        {"name": "inside", "path": "inside", "is_leaf": True, "children": []}
    ]
    assert home["stats"]["total_projects"] == 1
    assert home["recent_projects"][0]["path"] == "inside"
    assert home["preview_pool"] == []


def test_public_targets_reject_inside_link_components(tmp_path, schema_db):
    library = tmp_path / "library"
    project = library / "inside"
    alias = library / "inside-alias"
    library.mkdir()
    project.mkdir()
    (project / "asset.txt").write_text("asset", encoding="utf-8")
    try:
        alias.symlink_to(project, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory links are unavailable on this platform")

    service = _service(schema_db)
    config = ProjectDepthConfig(global_depth=1)

    with pytest.raises(ValueError, match="link or reparse"):
        service.list_projects(
            library, alias, depth_config=config, db_conn=schema_db
        )
    with pytest.raises(ValueError, match="link or reparse"):
        service.get_project_detail(
            library, alias, rel_path="inside-alias", db_conn=schema_db
        )


def test_project_service_rejects_target_replaced_during_listing(
    tmp_path, schema_db, monkeypatch
):
    library = tmp_path / "library"
    project = library / "inside"
    moved_project = library / "inside-original"
    library.mkdir()
    project.mkdir()
    (project / "asset.txt").write_text("asset", encoding="utf-8")

    service = _service(schema_db)
    original_entries = service._safe_directory_entries
    replaced = False

    def replace_after_admission(path):
        nonlocal replaced
        if not replaced and path == project:
            replaced = True
            project.rename(moved_project)
        return original_entries(path)

    monkeypatch.setattr(service, "_safe_directory_entries", replace_after_admission)
    try:
        with pytest.raises(ValueError, match="link or reparse"):
            service.list_projects(
                library,
                project,
                depth_config=ProjectDepthConfig(global_depth=1),
                db_conn=schema_db,
            )
    finally:
        if moved_project.exists():
            moved_project.rename(project)


def test_project_service_excludes_outside_directory_and_file_links(
    tmp_path, schema_db
):
    library = tmp_path / "library"
    outside = tmp_path / "outside-sentinel"
    project = library / "inside"
    linked_directory = library / "outside-directory"
    linked_file = project / "outside-sentinel.png"
    library.mkdir()
    project.mkdir()
    outside.mkdir()
    (project / "asset.txt").write_text("asset", encoding="utf-8")
    outside_image = outside / "outside-sentinel.png"
    outside_image.write_bytes(b"outside-content")
    try:
        linked_directory.symlink_to(outside, target_is_directory=True)
        linked_file.symlink_to(outside_image)
    except (OSError, NotImplementedError):
        pytest.skip("directory/file links are unavailable on this platform")

    service = _service(schema_db)
    config = ProjectDepthConfig(global_depth=1)

    with pytest.raises(ValueError):
        service.list_projects(
            library, linked_directory, depth_config=config, db_conn=schema_db
        )
    with pytest.raises(ValueError):
        service.get_project_detail(
            library, linked_directory, rel_path="outside-directory", db_conn=schema_db
        )

    listing = service.list_projects(library, library, depth_config=config, db_conn=schema_db).to_response()
    detail = service.get_project_detail(
        library, project, rel_path="inside", db_conn=schema_db
    ).to_response()
    tree = service.build_tree(library, depth_config=config).to_response()
    home = service.get_home(library, depth_config=config, db_conn=schema_db).to_response()

    assert [item["name"] for item in listing["items"]] == ["inside"]
    assert listing["items"][0]["file_count"] == 1
    assert listing["items"][0]["total_size"] == 5
    assert listing["items"][0]["thumbnail_path"] is None
    assert [file["name"] for file in detail["files"]] == ["asset.txt"]
    assert detail["file_count"] == 1
    assert detail["total_size"] == 5
    assert detail["images"] == []
    assert detail["thumbnail_path"] is None
    assert [node["name"] for node in tree["tree"]] == ["inside"]
    assert tree["tree"][0]["children"] == []
    assert home["stats"]["total_projects"] == 1
    assert [item["path"] for item in home["recent_projects"]] == ["inside"]
    assert home["preview_pool"] == []
    assert service.count_projects(library, depth_config=config) == 1
    serialized = repr((listing, detail, tree, home))
    assert "outside-sentinel" not in serialized
