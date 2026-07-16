# LAN First-Image Linear Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LAN directory previews select the same first image without allocating and sorting every image candidate.

**Architecture:** Keep `find_first_image(dir_path: Path) -> str | None` as the sole public helper and preserve its result contract: choose the file with the smallest case-insensitive name among direct child files whose suffix is in `IMAGE_EXTS`. Replace the temporary candidate list and `sorted()` call with one `os.scandir()` pass that retains the current best candidate. The helper continues to return `None` for an empty/non-image directory or an `OSError`.

**Tech Stack:** Python 3.14, `os.scandir`, `pathlib.Path`, pytest.

## Global Constraints

- Do not change LAN routes, response schemas, authentication, path validation, or callers.
- Preserve case-insensitive filename ordering exactly; do not choose filesystem enumeration order.
- Only direct regular files with suffixes in `IMAGE_EXTS` are eligible.
- Preserve the existing `OSError -> None` behavior.
- Follow TDD: focused test must fail before the helper implementation changes.
- Run focused tests before the full project quality gate.

---

### Task 1: Select LAN Preview Images in One Scan

**Files:**
- Modify: `AssetsManager/lan/routes/_helpers.py:356-365`
- Test: `tests/lan/test_helpers.py`

**Interfaces:**
- Consumes: `IMAGE_EXTS` and `find_first_image(dir_path: Path) -> str | None` in `AssetsManager.lan.routes._helpers`.
- Produces: The unchanged `find_first_image` return value without building or sorting a full candidate list.

- [ ] **Step 1: Write the failing test**

Add the helper import and this test to `tests/lan/test_helpers.py`:

```python
from pathlib import Path

from AssetsManager.lan.routes import _helpers
from AssetsManager.lan.routes._helpers import find_first_image


def test_find_first_image_does_not_sort_all_candidates(tmp_path: Path, monkeypatch):
    expected = tmp_path / "Apple.PNG"
    expected.write_bytes(b"a")
    (tmp_path / "zebra.jpg").write_bytes(b"z")
    (tmp_path / "middle.webp").write_bytes(b"m")

    def fail_sorted(*_args, **_kwargs):
        raise AssertionError("find_first_image must not sort candidates")

    monkeypatch.setattr(_helpers, "sorted", fail_sorted, raising=False)

    assert find_first_image(tmp_path) == str(expected)
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
python -m pytest tests/lan/test_helpers.py::test_find_first_image_does_not_sort_all_candidates -q
```

Expected: FAIL because the current helper calls `sorted()`.

- [ ] **Step 3: Write the minimal implementation**

Replace `find_first_image` with:

```python
def find_first_image(dir_path: Path) -> str | None:
    try:
        best_entry = None
        best_name = ""
        for entry in os.scandir(dir_path):
            if not entry.is_file() or Path(entry.name).suffix.lower() not in IMAGE_EXTS:
                continue
            name = entry.name.lower()
            if best_entry is None or name < best_name:
                best_entry = entry
                best_name = name
        return best_entry.path if best_entry is not None else None
    except OSError:
        return None
```

- [ ] **Step 4: Add behavior-equivalence coverage**

Add these tests to `tests/lan/test_helpers.py`:

```python
def test_find_first_image_uses_case_insensitive_filename_order(tmp_path: Path):
    (tmp_path / "zebra.jpg").write_bytes(b"z")
    expected = tmp_path / "Apple.PNG"
    expected.write_bytes(b"a")
    (tmp_path / "middle.webp").write_bytes(b"m")
    (tmp_path / "not-an-image.txt").write_text("ignore")

    assert find_first_image(tmp_path) == str(expected)


def test_find_first_image_ignores_nested_images_and_returns_none_without_direct_images(tmp_path: Path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "inside.jpg").write_bytes(b"image")

    assert find_first_image(tmp_path) is None
```

- [ ] **Step 5: Run focused LAN helper verification**

Run:

```powershell
python -m pytest tests/lan/test_helpers.py -q
```

Expected: all LAN helper tests pass, including the no-sort guard and direct-file-only behavior.

- [ ] **Step 6: Run the relevant LAN suite**

Run:

```powershell
python -m pytest tests/lan -q
```

Expected: all LAN tests pass; no route behavior changes.

- [ ] **Step 7: Commit the focused change**

```powershell
git add AssetsManager/lan/routes/_helpers.py tests/lan/test_helpers.py docs/compose/plans/2026-07-17-lan-first-image-linear-scan.md
git commit -m "perf: scan LAN preview images once"
```
