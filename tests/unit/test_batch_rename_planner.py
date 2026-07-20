import pytest

from AssetsManager.panels.file_list._batch_rename import plan_batch_rename


def test_plan_expands_name_counter_and_preserves_suffixes(tmp_path):
    plan = plan_batch_rename(
        [tmp_path / "b.png", tmp_path / "a.txt"],
        "{name}_{n}",
        occupied_paths=[],
        windows_rules=True,
    )

    assert [entry.target.name for entry in plan.entries] == ["a_1.txt", "b_2.png"]
    assert plan.is_valid


def test_plan_rejects_duplicate_and_existing_targets(tmp_path):
    existing = tmp_path / "same.txt"
    plan = plan_batch_rename(
        [tmp_path / "a.txt", tmp_path / "b.txt"],
        "same",
        occupied_paths=[existing],
        windows_rules=True,
    )

    assert not plan.is_valid
    assert all("duplicate_target" in entry.errors for entry in plan.entries)
    assert all("existing_target" in entry.errors for entry in plan.entries)


@pytest.mark.parametrize("name", ["bad:name", "CON", "con.txt", "name. ", "x" * 256])
def test_plan_rejects_windows_invalid_names(tmp_path, name):
    plan = plan_batch_rename(
        [tmp_path / "asset.txt"],
        name,
        occupied_paths=[],
        windows_rules=True,
    )

    assert not plan.is_valid
    assert plan.entries[0].errors


def test_plan_rejects_selected_source_as_target(tmp_path):
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    plan = plan_batch_rename(
        [first, second],
        "b",
        occupied_paths=[first, second],
        windows_rules=True,
    )

    assert "selected_source_target" in plan.entries[0].errors


def test_plan_keeps_unknown_template_text_literal(tmp_path):
    plan = plan_batch_rename(
        [tmp_path / "asset.txt"],
        "{name}_{date}_{n}",
        occupied_paths=[],
        windows_rules=True,
    )

    assert plan.entries[0].target.name == "asset_{date}_1.txt"
