"""Tests for ProjectService."""

from AssetsManager.application.project_service import ProjectDepthConfig, ProjectService


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
    assert response["items"][0]["thumbnail_url"] == "/api/thumbnails/alpha/cover.png"
    assert response["items"][0]["file_count"] == 2


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


def test_get_project_detail_returns_files_images_and_download_url(tmp_path, schema_db):
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
    assert detail["thumbnail_url"] == "/api/thumbnails/alpha/cover.png"
    assert detail["download_url"] == "/api/download/alpha"
    assert [file["name"] for file in detail["files"]] == ["cover.png", "readme.txt"]
    assert detail["images"] == [{
        "name": "cover.png",
        "url": "/api/thumbnails/alpha/cover.png?size=1920",
        "thumb_url": "/api/thumbnails/alpha/cover.png?size=512",
    }]


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
