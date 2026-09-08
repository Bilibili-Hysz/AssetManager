"""N2 recovery acceptance matrix — rows 1 to 5 (workpack 2026-09-14).

Row 1 — normal full backup/restore: a synthetic library with Chinese,
space and literal ``%`` paths is seeded with tags, notes, urls, rating
5 / 0 / NULL, favorites, a manual collection (with members) and a smart
collection (with a structured rule).  A complete RuntimeData backup ZIP is
created, validated, and restored into a NEW destination runtime domain
(fresh ``AM_RUNTIME_ROOT``, same library root path — the supported restore
target).  Assertions cover the ZIP manifest/digest gate, the raw-asset
contract (library-root files are NOT in the ZIP and are byte-identical
after restore), and the full DB projection round-trip.

Row 2 — metadata JSON export: the same seed is exported with
``export_metadata_json``.  Assertions pin the real contract observed in
``build_metadata_export``: exactly the stable-sorted relative path /
path_type / tags / notes / urls fields; Chinese and ``%`` paths intact;
rating/favorite/collection state explicitly NOT in the JSON contract;
atomic destination replacement.

Row 3 — restore overwrite semantics: a destination RuntimeData seeded with
a DIFFERENT projection (ratings 3/2/4, extra tags, extra collection member,
a destination-only collection, different notes) is overwritten from the
row-1 archive.  The archive state must become authoritative: rating 0 is
not swallowed as false, NULL does not fall back to the destination's old
value, and destination-side extra collection members are replaced by the
archive member set.  The old RuntimeData lands in the destination domain's
restore quarantine byte-identical, and the restore-intent marker is
observed (via a ``Path.replace`` observation point at the install swap) to
exist mid-flight with a usable rollback payload pointing at the quarantine
entry.

Row 4 — interrupted restore, then idempotent second restore: a child
process runs the same restore with ``Path.replace`` patched so the install
swap writes a barrier file and blocks; the parent kills the child inside
the two-step swap crash window (previous quarantined, marker written,
staging not yet installed).  A NEW process then opens the same runtime
domain: startup recovery must roll the quarantined previous RuntimeData
back byte-identically.  Finally the SAME archive is restored again
normally: the result matches the archive projection and exactly one
quarantine entry exists (no duplicate quarantine accumulation across the
interrupted + successful pair).

Row 5 — corrupt archive rejection, three negative cases: (a) one member's
bytes tampered (manifest digest mismatch), (b) truncated ``manifest.json``,
(c) a zip-slip member (``data/../evil.txt``).  Each restore must be
rejected during validation — before any state is written into the
destination domain: the old RuntimeData stays byte-identical, no staging
directory and no intent marker appear, the quarantine set is unchanged,
the error text is case-distinguishable, and the service is NOT poisoned.

Row 6 — fail-closed and self-heal boundaries: (a) a healthy marker whose
quarantine entry is missing/unusable keeps every open refused with an
actionable error and never materializes a half-restored or empty slot;
(b) a corrupt marker is self-healed — renamed in place with its bytes
preserved as evidence, the NEWEST valid quarantine candidate (slot-name
prefix + database integrity gate) auto-restored into the slot, and with
no valid candidate the open keeps failing closed across repeated opens
while ``restore_intent_status`` reports ``corrupt-quarantined``.

Row 7 — concurrency mutex, manual-disposal token contract and cycle
bounds: while a child process is parked inside the install swap crash
window, a second process receives the fail-fast ``LibraryAlreadyOpenError``
for open, restore and manual recovery (the actual lock contract is
tryLock(0) refusal, not queueing), and the crash-window evidence stays
intact; the manual surface refuses wrong tokens, refuses ACK while the
library is active, and refuses to ACK away a crash window whose slot is
absent; after three interrupted-restore/rollback cycles the quarantine is
drained each round and staging residue is bounded at exactly one leftover
per interrupted attempt (age-gated sweep keeps fresh residue in place).

Every scenario runs entirely inside ``tmp_path`` with a per-phase isolated
``AM_RUNTIME_ROOT``; user asset directories are never touched.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile

import pytest

import AssetsManager.application.library_export_io as export_io_module
from AssetsManager.application import ApplicationBootstrap
from AssetsManager.application.favorite_service import FavoriteService
from AssetsManager.core import path_resolver
from AssetsManager.core.library_lock import LibraryAlreadyOpenError
from AssetsManager.core.path_resolver import library_data_dir, root_identity

# Snapshot root (parent of tests/) — the child processes' PYTHONPATH/cwd so
# they import exactly this snapshot's production code.
SNAPSHOT_ROOT = Path(__file__).resolve().parents[2]

# The sweep's own staging-residue naming contract (library_service module
# constant mirrored here): one interrupted restore leaves exactly one of
# these behind, folded into quarantine only after the week-old age gate.
_STAGING_RESIDUE_PATTERN = (
    r"^\.{slot}\.restore-[0-9a-f]{{32}}$"
)

# Raw assets under the library root.  The directory name carries Chinese
# characters, a space and a literal percent sign — the encodings that the
# workpack requires to survive both products untouched.
LIBRARY_FILES: dict[str, bytes] = {
    "中文 50%/hero.png": b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4,
    "普通/scene.txt": "场景说明：普通目录\n".encode("utf-8"),
    "未评分/unrated.png": b"\x89PNG\r\n\x1a\n" + b"unrated" * 20,
}
OWNER_KEY = "tester"
MANUAL_COLLECTION = "普通集合"
SMART_COLLECTION = "高分图片"
SMART_QUERY = {"extensions": [".png"], "rating_min": 4}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_raw_assets(root: Path) -> None:
    for relative, content in LIBRARY_FILES.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _asset_paths(root: Path) -> dict[str, str]:
    """Relative POSIX path -> absolute path for the seeded raw assets."""
    return {relative: str(root / relative) for relative in LIBRARY_FILES}


def _walk_digests(root: Path) -> dict[str, str]:
    """Relative POSIX path -> SHA-256 for every file under *root*."""
    return {
        path.relative_to(root).as_posix(): _digest(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _seed_runtime_data(services, session, root: Path) -> dict[str, object]:
    """Write the full RuntimeData projection through the service layer."""
    tag_service = services.tag_service
    metadata_service = services.metadata_service
    # Favorites are principal-scoped and not exposed on LibraryScopedServices;
    # tests construct the service directly on the live session.
    favorite_service = FavoriteService(session=session)
    collection_service = services.collection_service

    paths = _asset_paths(root)
    hero, scene, unrated = paths["中文 50%/hero.png"], paths["普通/scene.txt"], (
        paths["未评分/unrated.png"]
    )

    tag_service.add_tag(root, hero, "主角")
    tag_service.add_tag(root, hero, "Hero")
    tag_service.add_tag(root, scene, "场景")
    tag_service.add_tag(root, scene, "alpha")
    tag_service.add_tag(root, scene, "Beta")
    tag_service.add_tag(root, unrated, "draft")

    metadata_service.set_notes(root, hero, "主角备注：中文内容 ✓")
    metadata_service.set_notes(root, scene, "plain scene note")
    metadata_service.set_notes(root, unrated, "未评分说明")
    metadata_service.add_url(root, hero, "https://example.test/a")
    metadata_service.add_url(root, hero, "https://example.test/b")
    metadata_service.add_url(root, scene, "https://example.test/scene")

    # Rating 5 / rating 0 / rating NULL (row exists via notes, never rated).
    metadata_service.set_rating(root, hero, 5)
    metadata_service.set_rating(root, scene, 0)

    favorite_service.add(root, OWNER_KEY, hero)
    favorite_service.add(root, OWNER_KEY, scene)

    manual = collection_service.create(root, MANUAL_COLLECTION)
    collection_service.add_files(root, manual["id"], [hero, scene])
    smart = collection_service.create_smart(root, SMART_COLLECTION, SMART_QUERY)

    # Populate the assets index so the smart collection can be evaluated.
    services.asset_index_service.index_directory_tree(root)

    return {
        "manual_id": manual["id"],
        "smart_id": smart["id"],
        "hero": hero,
        "scene": scene,
        "unrated": unrated,
    }


def _projection(conn: sqlite3.Connection) -> dict:
    """Full DB projection snapshot straight from RuntimeData SQLite."""
    tags = {
        (row[0], row[1])
        for row in conn.execute("SELECT file_path, tag FROM file_tags")
    }
    meta = {
        row[0]: {"notes": row[1], "urls": json.loads(row[2]), "rating": row[3]}
        for row in conn.execute("SELECT file_path, notes, urls, rating FROM file_meta")
    }
    favorites = {
        (row[0], row[1])
        for row in conn.execute("SELECT owner_key, file_path FROM library_favorites")
    }
    collections: dict[str, dict] = {}
    for collection_id, name, kind, query_json in conn.execute(
        "SELECT id, name, kind, query_json FROM asset_collections"
    ):
        members = {
            row[0]
            for row in conn.execute(
                "SELECT file_path FROM asset_collection_members WHERE collection_id=?",
                (collection_id,),
            )
        }
        collections[name] = {
            "kind": kind,
            "query_json": query_json,
            "members": members,
        }
    return {
        "tags": tags,
        "meta": meta,
        "favorites": favorites,
        "collections": collections,
    }


# ── Rows 3–5 shared helpers ──────────────────────────────────────

DEST_HERO_NOTES = "目的域旧备注：hero"
DEST_ONLY_COLLECTION = "目的域独有集合"


def _seed_destination_state(services, session, root: Path) -> None:
    """Write a DIFFERENT RuntimeData projection — the overwrite victim.

    Ratings deliberately differ from the archive tri-state (hero 5, scene 0,
    unrated NULL becomes 3 / 2 / 4) so a falsy ``rating or old_rating``
    restore would be caught by row 3; the manual collection gains an extra
    member and a destination-only collection exists so the archive member
    set must fully replace the destination's.
    """
    favorite_service = FavoriteService(session=session)
    tag_service = services.tag_service
    metadata_service = services.metadata_service
    collection_service = services.collection_service

    paths = _asset_paths(root)
    hero, scene, unrated = (
        paths["中文 50%/hero.png"],
        paths["普通/scene.txt"],
        paths["未评分/unrated.png"],
    )

    tag_service.add_tag(root, hero, "旧标签")
    metadata_service.set_notes(root, hero, DEST_HERO_NOTES)
    metadata_service.set_notes(root, scene, "目的域旧备注：scene")
    metadata_service.set_notes(root, unrated, "目的域旧备注：unrated")
    metadata_service.add_url(root, hero, "https://old.example.test/hero")
    metadata_service.set_rating(root, hero, 3)  # archive: 5
    metadata_service.set_rating(root, scene, 2)  # archive: 0
    metadata_service.set_rating(root, unrated, 4)  # archive: NULL
    favorite_service.add(root, OWNER_KEY, hero)

    manual = collection_service.create(root, MANUAL_COLLECTION)
    collection_service.add_files(root, manual["id"], [hero, scene, unrated])
    collection_service.create(root, DEST_ONLY_COLLECTION)
    services.asset_index_service.index_directory_tree(root)


def _jsonable_projection(projection: dict) -> dict:
    """JSON-safe shaping of :func:`_projection` output (sets -> sorted lists)."""
    return {
        "tags": sorted([list(tag) for tag in projection["tags"]]),
        "meta": projection["meta"],
        "favorites": sorted([list(row) for row in projection["favorites"]]),
        "collections": {
            name: {**info, "members": sorted(info["members"])}
            for name, info in projection["collections"].items()
        },
    }


def _sqlite_ratings(database_file: Path) -> dict[str, object]:
    """Read file_meta ratings from a database file without touching it."""
    connection = sqlite3.connect(
        f"{database_file.as_uri()}?mode=ro", uri=True
    )
    try:
        return {
            row[0]: row[1]
            for row in connection.execute("SELECT file_path, rating FROM file_meta")
        }
    finally:
        connection.close()


def _stable_digests(root: Path) -> dict[str, str]:
    """:func:`_walk_digests` without SQLite's transient ``-wal``/``-shm`` files."""
    return {
        relative: digest
        for relative, digest in _walk_digests(root).items()
        if not (relative.endswith("-wal") or relative.endswith("-shm"))
    }


def _quarantine_entries(data_dir: Path) -> list[Path]:
    """RuntimeData_* entries in this library's restore quarantine."""
    quarantine_root = data_dir.parent / "_orphaned" / "restore-backups"
    if not quarantine_root.is_dir():
        return []
    return sorted(
        entry
        for entry in quarantine_root.iterdir()
        if entry.is_dir() and entry.name.startswith(data_dir.name + "_")
    )


def _assert_no_restore_residue(data_dir: Path) -> None:
    """No staging directory, no intent marker at the destination domain."""
    assert not export_io_module.restore_intent_path(data_dir).exists()
    assert list(data_dir.parent.glob(f".{data_dir.name}.restore-*")) == []


def _make_corrupt_archive(original: Path, destination: Path, corruption: str) -> Path:
    """Rebuild *original* with one deterministic corruption applied."""
    with zipfile.ZipFile(original) as source_archive:
        payloads = [
            (info.filename, source_archive.read(info.filename))
            for info in source_archive.infolist()
        ]

    def tamper(name: str, payload: bytes) -> bytes:
        if name != "data/assetmanager.db":
            return payload
        middle = len(payload) // 2
        return payload[:middle] + bytes((payload[middle] ^ 0xFF,)) + payload[middle + 1 :]

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, payload in payloads:
            if corruption == "tampered-member":
                payload = tamper(name, payload)
            elif corruption == "truncated-manifest" and name == "manifest.json":
                payload = payload[: len(payload) // 2]
            target.writestr(name, payload)
        if corruption == "zip-slip-member":
            target.writestr("data/../evil.txt", b"zip-slip-probe")
    return destination


# ── Row 4 child process scripts ──────────────────────────────────

# Child #1: restore with the install swap blocked.  The interception is
# precise (staging-named source whose target is the data-dir slot), so the
# quarantine replace and every unrelated Path.replace pass through.
CHILD_INTERRUPTED_RESTORE_SCRIPT = r"""
import sys
import time
from pathlib import Path

LIBRARY = Path(sys.argv[1])
ARCHIVE = Path(sys.argv[2])
BARRIER = Path(sys.argv[3])

from AssetsManager.application import ApplicationBootstrap
from AssetsManager.core.path_resolver import library_data_dir

_DATA_DIR_NAME = library_data_dir(LIBRARY).name
_real_replace = Path.replace


def _blocking_replace(self, target, *, _real=_real_replace):
    if (
        self.name.startswith("." + _DATA_DIR_NAME + ".restore-")
        and Path(target).name == _DATA_DIR_NAME
    ):
        print("install-blocked", flush=True)
        BARRIER.write_text("install", encoding="utf-8")
        time.sleep(600)  # killed by the parent inside the crash window
    return _real(self, target)


Path.replace = _blocking_replace

bootstrap = ApplicationBootstrap()
session = bootstrap.library_service.open_session(LIBRARY)
services = bootstrap.runtime_for(session).services
bootstrap.library_service.close_session(session)
print("restore-started", flush=True)
result = services.export_service.restore_backup(
    ARCHIVE, LIBRARY, overwrite_existing=True
)
print(f"restore-unexpectedly-completed: {result}", flush=True)
"""

# Child #2: the NEW process opening the same runtime domain.  Startup
# recovery must roll the quarantined previous RuntimeData back before the
# database opens; the report records pre-open evidence, the post-open
# projection and digests for the parent to assert on.
CHILD_RECOVERY_OPEN_SCRIPT = r"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

LIBRARY = Path(sys.argv[1])
REPORT = Path(sys.argv[2])

from AssetsManager.application import ApplicationBootstrap
from AssetsManager.application.library_export_io import restore_intent_path
from AssetsManager.core.path_resolver import library_data_dir


def walk_digests(root):
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def jsonable_projection(conn):
    tags = sorted([list(row) for row in conn.execute(
        "SELECT file_path, tag FROM file_tags")])
    meta = {
        row[0]: {"notes": row[1], "urls": json.loads(row[2]), "rating": row[3]}
        for row in conn.execute("SELECT file_path, notes, urls, rating FROM file_meta")
    }
    favorites = sorted([list(row) for row in conn.execute(
        "SELECT owner_key, file_path FROM library_favorites")])
    collections = {}
    for collection_id, name, kind, query_json in conn.execute(
        "SELECT id, name, kind, query_json FROM asset_collections"
    ):
        members = sorted(row[0] for row in conn.execute(
            "SELECT file_path FROM asset_collection_members WHERE collection_id=?",
            (collection_id,),
        ))
        collections[name] = {"kind": kind, "query_json": query_json, "members": members}
    return {"tags": tags, "meta": meta, "favorites": favorites, "collections": collections}


data_dir = library_data_dir(LIBRARY)
marker = restore_intent_path(data_dir)
report = {
    "marker_before_open": marker.exists(),
    "data_dir_before_open": data_dir.exists(),
}
if marker.exists():
    report["marker_payload"] = json.loads(marker.read_text(encoding="utf-8"))

bootstrap = ApplicationBootstrap()
session = bootstrap.library_service.open_session(LIBRARY)
report["projection"] = jsonable_projection(session.connection_for())
report["marker_after_open"] = restore_intent_path(data_dir).exists()
report["data_dir_restored"] = data_dir.exists()
bootstrap.library_service.close()
# Digests after the clean close: the connection's -wal/-shm side files are
# gone, so this matches the pre-restore snapshot's conditions exactly.
report["digests"] = walk_digests(data_dir)
REPORT.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
print("recovery-open-done", flush=True)
"""


def _spawn_blocked_restore(
    tmp_path: Path,
    tag: str,
    library: Path,
    archive: Path,
    runtime_root_dir: Path,
) -> tuple[subprocess.Popen, Path, Path]:
    """Start a child restore parked in the install swap; return (proc, barrier, log)."""
    script = tmp_path / f"child-interrupted-{tag}.py"
    script.write_text(CHILD_INTERRUPTED_RESTORE_SCRIPT, encoding="utf-8")
    barrier = tmp_path / f"barrier-{tag}.txt"
    log_path = tmp_path / f"child-{tag}.log"
    child_env = os.environ.copy()
    child_env["AM_RUNTIME_ROOT"] = str(runtime_root_dir)
    child_env["PYTHONPATH"] = str(SNAPSHOT_ROOT)
    with log_path.open("w", encoding="utf-8") as log_handle:
        child = subprocess.Popen(
            [sys.executable, str(script), str(library), str(archive), str(barrier)],
            cwd=str(SNAPSHOT_ROOT),
            env=child_env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 180
        while not barrier.exists():
            if child.poll() is not None:
                raise AssertionError(
                    f"child {tag} exited before the install barrier:\n"
                    + log_path.read_text(encoding="utf-8")
                )
            if time.monotonic() > deadline:
                child.kill()
                child.wait(timeout=30)
                raise AssertionError(
                    f"timed out waiting for the install barrier ({tag}):\n"
                    + log_path.read_text(encoding="utf-8")
                )
            time.sleep(0.05)
    return child, barrier, log_path


def _kill_blocked_restore(child: subprocess.Popen) -> None:
    """Kill the parked child inside the crash window (simulated process death)."""
    child.kill()
    child.wait(timeout=30)


def _staging_residue(data_dir: Path) -> list[Path]:
    """Fresh staging leftovers of interrupted restores for this slot.

    Mirrors the sweep's own naming contract: ``.{slot}.restore-<32hex>``.
    """
    pattern = re.compile(
        _STAGING_RESIDUE_PATTERN.format(slot=re.escape(data_dir.name))
    )
    return sorted(
        entry
        for entry in data_dir.parent.iterdir()
        if pattern.match(entry.name) and entry.is_dir()
    )


def _make_quarantine_candidate(
    data_dir: Path, name_suffix: str, sentinel: str, mtime_shift: float
) -> Path:
    """Copy the current slot into a quarantine candidate under its naming contract."""
    candidate = (
        data_dir.parent
        / "_orphaned"
        / "restore-backups"
        / f"{data_dir.name}_{name_suffix}"
    )
    candidate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(data_dir, candidate)
    (candidate / "sentinel.txt").write_text(sentinel, encoding="utf-8")
    stale = time.time() + mtime_shift
    os.utime(candidate, (stale, stale))
    return candidate


@pytest.fixture()
def runtime_domain(tmp_path, monkeypatch):
    """Return a callable that re-points the process runtime domain.

    Each call installs a fresh isolated ``AM_RUNTIME_ROOT`` under tmp_path
    (env var + the resolver function used by every caller), so a test can
    move from a source runtime domain to a destination runtime domain
    without ever touching a real asset or user directory.
    """
    installed: list[Path] = []

    def install(name: str) -> Path:
        domain = tmp_path / f"runtime-{name}"
        domain.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("AM_RUNTIME_ROOT", str(domain))
        monkeypatch.setattr(path_resolver, "runtime_root", lambda: domain)
        installed.append(domain)
        return domain

    return install


def test_row1_full_backup_restore_round_trip(tmp_path, runtime_domain):
    library = tmp_path / "library"
    library.mkdir()
    _write_raw_assets(library)
    expected_assets = _walk_digests(library)

    # ── Source runtime domain: seed, snapshot the projection, back up ──
    runtime_domain("source")
    bootstrap = ApplicationBootstrap()
    try:
        session = bootstrap.library_service.open_session(library)
        services = bootstrap.runtime_for(session).services
        root = session.root
        ids = _seed_runtime_data(services, session, root)
        projection_before = _projection(session.connection_for())
        smart_before = [
            entry.file_path
            for entry in services.collection_service.evaluate(
                root, ids["smart_id"], limit=100
            )
        ]
        favorites_before = FavoriteService(session=session).list_paths(
            root, OWNER_KEY
        )

        # Non-vacuity guards: the seed actually landed before we compare.
        assert len(projection_before["tags"]) >= 6
        assert set(projection_before["meta"]) == set(_asset_paths(root).values())
        assert projection_before["favorites"]
        assert projection_before["collections"][MANUAL_COLLECTION]["members"]
        assert smart_before == [_asset_paths(root)["中文 50%/hero.png"]]

        archive = tmp_path / "artifacts" / "library_backup.assetbackup.zip"
        backup_result = services.export_service.create_backup(root, archive)
        archive_digest = _digest(archive.read_bytes())

        # ZIP manifest/digest gate on the generated archive.
        with zipfile.ZipFile(archive) as archive_file:
            names = set(archive_file.namelist())
            manifest = json.loads(archive_file.read("manifest.json"))
            for entry in manifest["files"]:
                member = archive_file.read(entry["path"])
                assert _digest(member) == entry["sha256"]
                assert len(member) == entry["size"]
        member_names = {entry["path"] for entry in manifest["files"]}
        assert names == member_names | {"manifest.json"}
        assert "data/assetmanager.db" in member_names
        # The raw-asset contract: library-root files are NOT backup members.
        assert not any(relative in names for relative in LIBRARY_FILES)

        validation = services.export_service.validate_backup(
            archive, expected_library_root=root
        )
        assert validation.valid
        assert validation.errors == ()
        assert validation.file_count == backup_result.file_count
        assert validation.database_quick_check == "ok"
    finally:
        bootstrap.library_service.close()

    # ── Destination runtime domain: restore and verify ──
    destination_runtime = runtime_domain("destination")
    bootstrap_b = ApplicationBootstrap()
    try:
        session_b = bootstrap_b.library_service.open_session(library)
        service_b = bootstrap_b.runtime_for(session_b).services.export_service
        # Fresh empty slot in the destination runtime domain.
        assert session_b.data_dir.is_relative_to(destination_runtime)
        bootstrap_b.library_service.close_session(session_b)

        restore_result = service_b.restore_backup(
            archive, library, overwrite_existing=True
        )
        assert restore_result.data_dir.is_relative_to(destination_runtime)
        assert restore_result.previous_data_dir is not None
        assert restore_result.previous_data_dir.is_dir()
        assert restore_result.file_count == backup_result.file_count
        # The archive itself was consumed read-only.
        assert _digest(archive.read_bytes()) == archive_digest

        reopened = bootstrap_b.library_service.open_session(library)
        services_b = bootstrap_b.runtime_for(reopened).services

        # Re-validation against the destination domain.
        revalidation = service_b.validate_backup(
            archive, expected_library_root=reopened.root
        )
        assert revalidation.valid
        assert revalidation.database_quick_check == "ok"

        # Raw-asset contract: same relative paths, byte-identical content.
        assert _walk_digests(library) == expected_assets
        for relative, content in LIBRARY_FILES.items():
            assert (library / relative).read_bytes() == content

        # Full DB projection round-trip: tags, notes, urls, ratings
        # (5 / 0 / NULL kept distinct), favorites, collections.
        projection_after = _projection(reopened.connection_for())
        assert projection_after == projection_before

        paths = _asset_paths(reopened.root)
        hero, scene, unrated = (
            paths["中文 50%/hero.png"],
            paths["普通/scene.txt"],
            paths["未评分/unrated.png"],
        )
        meta_after = projection_after["meta"]
        assert meta_after[hero]["rating"] == 5
        assert meta_after[scene]["rating"] == 0
        assert meta_after[scene]["rating"] is not None  # 0 is not falsy-loss
        assert meta_after[unrated]["rating"] is None  # NULL stays NULL
        assert meta_after[hero]["notes"] == "主角备注：中文内容 ✓"
        assert meta_after[hero]["urls"] == [
            "https://example.test/a",
            "https://example.test/b",
        ]
        assert meta_after[scene]["urls"] == ["https://example.test/scene"]

        favorites_after = FavoriteService(session=reopened).list_paths(
            reopened.root, OWNER_KEY
        )
        assert favorites_after == favorites_before

        # Manual collection members and smart collection rule survived.
        collections = projection_after["collections"]
        assert collections[MANUAL_COLLECTION]["members"] == {hero, scene}
        assert json.loads(collections[SMART_COLLECTION]["query_json"]) == SMART_QUERY

        # Smart collection re-evaluates to the same result after restore.
        smart_after = [
            entry.file_path
            for entry in services_b.collection_service.evaluate(
                reopened.root, ids["smart_id"], limit=100
            )
        ]
        assert smart_after == smart_before
        assert set(smart_before) == {hero}  # rating_min=4 keeps 0/NULL out

        # Restore intent marker consumed on success.
        assert not export_io_module.restore_intent_path(
            reopened.data_dir
        ).exists()
    finally:
        bootstrap_b.library_service.close()


def test_row2_metadata_json_export_contract(tmp_path, runtime_domain):
    library = tmp_path / "library"
    library.mkdir()
    _write_raw_assets(library)
    runtime_domain("main")
    bootstrap = ApplicationBootstrap()
    try:
        session = bootstrap.library_service.open_session(library)
        services = bootstrap.runtime_for(session).services
        root = session.root
        _seed_runtime_data(services, session, root)

        destination = tmp_path / "exports" / "nested" / "metadata.json"
        result = services.export_service.export_metadata_json(root, destination)

        assert result.destination == destination
        assert result.bytes_written == destination.stat().st_size
        raw = destination.read_bytes()
        payload = json.loads(raw.decode("utf-8"))

        # Top-level contract keys, exactly as implemented.
        assert set(payload) == {
            "format",
            "schema_version",
            "exported_at",
            "library",
            "entries",
        }
        assert payload["format"] == "assetsmanager.metadata"
        assert payload["schema_version"] == 1
        assert payload["library"]["path_format"] == "relative-to-library-root"

        entries = payload["entries"]
        assert len(entries) == len(LIBRARY_FILES)
        paths = [entry["path"] for entry in entries]
        assert paths == sorted(paths, key=lambda p: (p.casefold(), p))
        assert set(paths) == set(LIBRARY_FILES)
        for entry in entries:
            # Per-entry contract: the exact implemented field set.  Rating,
            # favorite and collection state are NOT part of the JSON export
            # contract (build_metadata_export collects notes/urls + tags).
            assert set(entry) == {"path", "path_type", "tags", "notes", "urls"}
            assert entry["path_type"] == "relative"

        by_path = {entry["path"]: entry for entry in entries}
        assert "中文 50%/hero.png" in by_path
        assert "普通/scene.txt" in by_path
        assert "未评分/unrated.png" in by_path

        # Entries match the stored DB rows exactly (stable, sorted tags).
        conn = session.connection_for()
        stored_tags: dict[str, list[str]] = {}
        for file_path, tag in conn.execute("SELECT file_path, tag FROM file_tags"):
            stored_tags.setdefault(file_path, []).append(tag)
        stored_meta = {
            row[0]: {"notes": row[1], "urls": json.loads(row[2])}
            for row in conn.execute("SELECT file_path, notes, urls FROM file_meta")
        }
        for relative, entry in by_path.items():
            absolute = str(root / relative)
            assert entry["tags"] == sorted(
                set(stored_tags.get(absolute, [])),
                key=lambda tag: (tag.casefold(), tag),
            )
            assert entry["notes"] == stored_meta[absolute]["notes"]
            assert entry["urls"] == stored_meta[absolute]["urls"]

        # Chinese and literal '%' paths survive as raw UTF-8 (no \u escapes).
        assert "中文 50%/hero.png".encode("utf-8") in raw
        assert "未评分说明".encode("utf-8") in raw
        assert b"50%" in raw
        assert b"\\u" not in raw

        # Rating / favorite / collection state is absent from the payload:
        # no such keys on entries and no such words anywhere in the JSON.
        serialized = json.dumps(payload, ensure_ascii=False)
        assert "rating" not in serialized
        assert "favorite" not in serialized
        assert "collection" not in serialized

        # Atomic destination replacement: re-export over the same target
        # fully replaces it and leaves no temporary residue.
        services.metadata_service.set_notes(
            root, root / "普通" / "scene.txt", "更新后的备注 第二版"
        )
        second = services.export_service.export_metadata_json(root, destination)
        assert second.entry_count == result.entry_count
        assert second.bytes_written == destination.stat().st_size
        payload2 = json.loads(destination.read_bytes().decode("utf-8"))
        scene_entry = next(
            entry
            for entry in payload2["entries"]
            if entry["path"] == "普通/scene.txt"
        )
        assert scene_entry["notes"] == "更新后的备注 第二版"
        assert not list(destination.parent.glob(".metadata.json.*.tmp"))
    finally:
        bootstrap.library_service.close()


def test_row3_restore_overwrite_semantics(tmp_path, runtime_domain, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    _write_raw_assets(library)
    expected_assets = _walk_digests(library)

    # ── Source runtime domain: seed the archive-authoritative state ──
    runtime_domain("source")
    bootstrap = ApplicationBootstrap()
    try:
        session = bootstrap.library_service.open_session(library)
        services = bootstrap.runtime_for(session).services
        root = session.root
        _seed_runtime_data(services, session, root)
        projection_archive = _projection(session.connection_for())

        archive = tmp_path / "artifacts" / "library_backup.assetbackup.zip"
        backup_result = services.export_service.create_backup(root, archive)
        validation = services.export_service.validate_backup(
            archive, expected_library_root=root
        )
        assert validation.valid
    finally:
        bootstrap.library_service.close()

    # ── Destination runtime domain: a DIFFERENT pre-existing state ──
    destination_runtime = runtime_domain("destination")
    bootstrap_b = ApplicationBootstrap()
    try:
        session_b = bootstrap_b.library_service.open_session(library)
        services_b = bootstrap_b.runtime_for(session_b).services
        root_b = session_b.root
        _seed_destination_state(services_b, session_b, root_b)
        projection_dest = _projection(session_b.connection_for())
        data_dir = session_b.data_dir
        assert data_dir.is_relative_to(destination_runtime)
        bootstrap_b.library_service.close_session(session_b)

        # Non-vacuity: the victim state really differs from the archive.
        paths = _asset_paths(root_b)
        hero, scene, unrated = (
            paths["中文 50%/hero.png"],
            paths["普通/scene.txt"],
            paths["未评分/unrated.png"],
        )
        assert projection_dest["meta"][hero]["rating"] == 3
        assert projection_dest["meta"][scene]["rating"] == 2
        assert projection_dest["meta"][unrated]["rating"] == 4
        assert projection_dest["collections"][MANUAL_COLLECTION]["members"] == {
            hero,
            scene,
            unrated,
        }
        assert DEST_ONLY_COLLECTION in projection_dest["collections"]
        old_digests = _walk_digests(data_dir)

        # Observe the crash-window contract at the install swap: the intent
        # marker must exist and reference the quarantine entry + staging
        # (the rollback evidence) before the staging replace commits.
        observed: dict[str, object] = {}
        real_replace = Path.replace

        def observing_replace(self, target):
            if ".restore-" in self.name and Path(target).name == data_dir.name:
                marker = export_io_module.restore_intent_path(data_dir)
                observed["marker_exists"] = marker.exists()
                observed["payload"] = json.loads(marker.read_text(encoding="utf-8"))
                observed["staging"] = str(self)
            return real_replace(self, target)

        monkeypatch.setattr(Path, "replace", observing_replace)

        restore_result = services_b.export_service.restore_backup(
            archive, library, overwrite_existing=True
        )
        assert restore_result.file_count == backup_result.file_count

        # ── Old RuntimeData isolated in the destination quarantine ──
        previous = restore_result.previous_data_dir
        assert previous is not None
        assert previous.parent == data_dir.parent / "_orphaned" / "restore-backups"
        assert previous.name.startswith(data_dir.name + "_")
        assert _walk_digests(previous) == old_digests
        # The quarantined copy still carries the OLD projection values.
        old_ratings = _sqlite_ratings(previous / "assetmanager.db")
        assert old_ratings[hero] == 3
        assert old_ratings[scene] == 2
        assert old_ratings[unrated] == 4
        assert _quarantine_entries(data_dir) == [previous]

        # ── The marker existed mid-flight, usable for rollback ──
        assert observed["marker_exists"] is True
        payload = observed["payload"]
        assert payload["version"] == 1
        assert payload["data_dir_name"] == data_dir.name
        assert payload["token"]
        assert payload["staging"] == observed["staging"]
        assert payload["quarantine_entry"] == str(previous)
        assert Path(payload["quarantine_entry"]).is_dir()

        # ── Archive state is now authoritative ──
        reopened = bootstrap_b.library_service.open_session(library)
        services_r = bootstrap_b.runtime_for(reopened).services
        projection_after = _projection(reopened.connection_for())
        assert projection_after == projection_archive

        meta_after = projection_after["meta"]
        assert meta_after[hero]["rating"] == 5
        assert meta_after[scene]["rating"] == 0  # 0 not swallowed as false
        assert meta_after[scene]["rating"] is not None
        assert meta_after[unrated]["rating"] is None  # NULL, not old 4
        assert meta_after[hero]["notes"] == "主角备注：中文内容 ✓"
        assert meta_after[hero]["urls"] == [
            "https://example.test/a",
            "https://example.test/b",
        ]
        assert projection_after["tags"] == projection_archive["tags"]
        assert set(projection_after["collections"]) == {
            MANUAL_COLLECTION,
            SMART_COLLECTION,
        }
        assert projection_after["collections"][MANUAL_COLLECTION]["members"] == {
            hero,
            scene,
        }  # destination's extra member replaced by the archive member set

        # Raw assets untouched by the overwrite restore.
        assert _walk_digests(library) == expected_assets
        # Success consumed the marker; no staging residue.
        assert not export_io_module.restore_intent_path(data_dir).exists()
        assert list(data_dir.parent.glob(f".{data_dir.name}.restore-*")) == []
    finally:
        bootstrap_b.library_service.close()


def test_row4_interrupted_restore_then_idempotent(tmp_path, runtime_domain):
    library = tmp_path / "library"
    library.mkdir()
    _write_raw_assets(library)
    expected_assets = _walk_digests(library)

    # ── Source runtime domain: seed and create the shared archive ──
    runtime_domain("source")
    bootstrap = ApplicationBootstrap()
    try:
        session = bootstrap.library_service.open_session(library)
        services = bootstrap.runtime_for(session).services
        root = session.root
        _seed_runtime_data(services, session, root)
        projection_archive = _projection(session.connection_for())

        archive = tmp_path / "artifacts" / "library_backup.assetbackup.zip"
        backup_result = services.export_service.create_backup(root, archive)
        assert services.export_service.validate_backup(
            archive, expected_library_root=root
        ).valid
    finally:
        bootstrap.library_service.close()

    # ── Destination runtime domain: seed the overwrite victim state ──
    destination_runtime = runtime_domain("destination")
    bootstrap_b = ApplicationBootstrap()
    try:
        session_b = bootstrap_b.library_service.open_session(library)
        services_b = bootstrap_b.runtime_for(session_b).services
        _seed_destination_state(services_b, session_b, session_b.root)
        projection_dest = _projection(session_b.connection_for())
        data_dir = session_b.data_dir
        assert data_dir.is_relative_to(destination_runtime)
        bootstrap_b.library_service.close_session(session_b)
    finally:
        bootstrap_b.library_service.close()
    old_digests = _walk_digests(data_dir)

    # ── Child #1: restore blocked inside the install swap, then killed ──
    child_script = tmp_path / "child_interrupted_restore.py"
    child_script.write_text(CHILD_INTERRUPTED_RESTORE_SCRIPT, encoding="utf-8")
    barrier = tmp_path / "install-barrier.txt"
    child_log = tmp_path / "child-restore.log"
    child_env = os.environ.copy()
    child_env["AM_RUNTIME_ROOT"] = str(destination_runtime)
    child_env["PYTHONPATH"] = str(SNAPSHOT_ROOT)
    with child_log.open("w", encoding="utf-8") as log_handle:
        child = subprocess.Popen(
            [
                sys.executable,
                str(child_script),
                str(library),
                str(archive),
                str(barrier),
            ],
            cwd=str(SNAPSHOT_ROOT),
            env=child_env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 180
        while not barrier.exists():
            if child.poll() is not None:
                raise AssertionError(
                    "child exited before the install barrier:\n"
                    + child_log.read_text(encoding="utf-8")
                )
            if time.monotonic() > deadline:
                child.kill()
                child.wait(timeout=30)
                raise AssertionError(
                    "timed out waiting for the install barrier:\n"
                    + child_log.read_text(encoding="utf-8")
                )
            time.sleep(0.05)
        child.kill()
        child.wait(timeout=30)
    assert barrier.read_text(encoding="utf-8") == "install"

    # ── Crash-window evidence: swap was interrupted between replaces ──
    assert not data_dir.exists()
    marker = export_io_module.restore_intent_path(data_dir)
    assert marker.exists()
    marker_payload = json.loads(marker.read_text(encoding="utf-8"))
    quarantined_previous = Path(marker_payload["quarantine_entry"])
    assert quarantined_previous.is_dir()
    assert _walk_digests(quarantined_previous) == old_digests

    # ── NEW process opens the same runtime domain: startup recovery ──
    recovery_script = tmp_path / "child_recovery_open.py"
    recovery_script.write_text(CHILD_RECOVERY_OPEN_SCRIPT, encoding="utf-8")
    recovery_report_path = tmp_path / "recovery-report.json"
    recovery_log = tmp_path / "child-recovery.log"
    with recovery_log.open("w", encoding="utf-8") as log_handle:
        recovery_child = subprocess.Popen(
            [sys.executable, str(recovery_script), str(library), str(recovery_report_path)],
            cwd=str(SNAPSHOT_ROOT),
            env=child_env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        recovery_child.wait(timeout=180)
    assert recovery_child.returncode == 0, recovery_log.read_text(encoding="utf-8")
    report = json.loads(recovery_report_path.read_text(encoding="utf-8"))
    assert report["marker_before_open"] is True
    assert report["marker_payload"]["quarantine_entry"] == str(quarantined_previous)
    assert report["data_dir_restored"] is True
    assert report["marker_after_open"] is False
    assert report["digests"] == old_digests
    assert report["projection"] == _jsonable_projection(projection_dest)
    # The rollback drained the quarantine: no duplicate copies left behind.
    assert _quarantine_entries(data_dir) == []

    # ── Same archive, second normal restore (idempotent) ──
    bootstrap_c = ApplicationBootstrap()
    try:
        session_c = bootstrap_c.library_service.open_session(library)
        services_c = bootstrap_c.runtime_for(session_c).services
        bootstrap_c.library_service.close_session(session_c)

        restore_result = services_c.export_service.restore_backup(
            archive, library, overwrite_existing=True
        )
        assert restore_result.file_count == backup_result.file_count
        previous = restore_result.previous_data_dir
        assert previous is not None and previous.is_dir()
        assert _walk_digests(previous) == old_digests
        assert services_c.export_service.restore_failure_state is None

        reopened = bootstrap_c.library_service.open_session(library)
        projection_after = _projection(reopened.connection_for())
        assert projection_after == projection_archive
        assert not export_io_module.restore_intent_path(data_dir).exists()
        # Exactly one RuntimeData_* quarantine entry across the interrupted
        # and the successful restore pair — no duplicate accumulation.
        assert _quarantine_entries(data_dir) == [previous]
        assert _walk_digests(library) == expected_assets
    finally:
        bootstrap_c.library_service.close()


@pytest.mark.parametrize(
    ("corruption", "expected_fragment"),
    [
        ("tampered-member", "checksum mismatch"),
        ("truncated-manifest", "Invalid backup manifest"),
        ("zip-slip-member", "Unsafe backup member path"),
    ],
)
def test_row5_corrupt_archive_rejected(
    tmp_path, runtime_domain, corruption, expected_fragment
):
    library = tmp_path / "library"
    library.mkdir()
    _write_raw_assets(library)

    # ── Source runtime domain: a valid archive to corrupt ──
    runtime_domain("source")
    bootstrap = ApplicationBootstrap()
    try:
        session = bootstrap.library_service.open_session(library)
        services = bootstrap.runtime_for(session).services
        root = session.root
        _seed_runtime_data(services, session, root)
        archive = tmp_path / "artifacts" / "library_backup.assetbackup.zip"
        services.export_service.create_backup(root, archive)
    finally:
        bootstrap.library_service.close()

    corrupt_archive = _make_corrupt_archive(
        archive, tmp_path / "artifacts" / f"corrupted-{corruption}.zip", corruption
    )
    # The archive bytes themselves are never modified in place.
    assert _digest(corrupt_archive.read_bytes()) != _digest(archive.read_bytes())

    # ── Destination runtime domain: rich old state that must survive ──
    runtime_domain("destination")
    bootstrap_b = ApplicationBootstrap()
    try:
        session_b = bootstrap_b.library_service.open_session(library)
        services_b = bootstrap_b.runtime_for(session_b).services
        _seed_destination_state(services_b, session_b, session_b.root)
        data_dir = session_b.data_dir
        service_b = services_b.export_service
        bootstrap_b.library_service.close_session(session_b)
        old_digests = _walk_digests(data_dir)
        quarantine_before = _quarantine_entries(data_dir)

        # The validate surface itself reports the case-distinguishable error.
        validation = service_b.validate_backup(
            corrupt_archive, expected_library_root=library
        )
        assert validation.valid is False
        assert expected_fragment in " ".join(validation.errors)

        # restore rejects during validation, before any destination write.
        with pytest.raises(ValueError, match=expected_fragment):
            service_b.restore_backup(corrupt_archive, library, overwrite_existing=True)
        # Rejected, not poisoned: the service stays usable.
        assert service_b.restore_failure_state is None

        # ── Destination domain byte-for-byte unchanged ──
        assert _walk_digests(data_dir) == old_digests
        assert _quarantine_entries(data_dir) == quarantine_before
        _assert_no_restore_residue(data_dir)
    finally:
        bootstrap_b.library_service.close()


def test_row6_recovery_failclosed_and_selfheal(tmp_path, runtime_domain):
    library = tmp_path / "library6"
    library.mkdir()
    runtime_domain("row6")
    bootstrap = ApplicationBootstrap()
    try:
        data_dir = library_data_dir(library)
        marker_path = export_io_module.restore_intent_path(data_dir)
        quarantine_before_row6 = _quarantine_entries(data_dir)

        def fresh_slot() -> None:
            session = bootstrap.library_service.open_session(library)
            bootstrap.library_service.close_session(session)

        fresh_slot()
        healthy_digests = _walk_digests(data_dir)

        # ── (a) healthy marker + missing quarantine entry → fail closed ──
        hold_a = data_dir.parent / "row6-hold-a"
        data_dir.replace(hold_a)  # crash window: slot absent
        missing_entry = data_dir.parent / f"{data_dir.name}_missing"
        token_a = export_io_module.write_restore_intent(
            data_dir,
            map_key=root_identity(library).map_key,
            quarantine_entry=missing_entry,
            staging=data_dir.parent / f".{data_dir.name}.restore-deadbeef",
        )
        with pytest.raises(RuntimeError) as excinfo_a:
            bootstrap.library_service.open_session(library)
        message_a = str(excinfo_a.value)
        assert "Interrupted library restore detected" in message_a
        assert "Refusing to open" in message_a  # actionable guidance present
        # No half-restored state: slot absent, marker untouched, no staging,
        # quarantine unchanged, and the isolated state stays byte-identical.
        assert not data_dir.exists()
        assert marker_path.exists()
        assert json.loads(marker_path.read_text(encoding="utf-8"))["token"] == token_a
        assert _quarantine_entries(data_dir) == quarantine_before_row6
        assert _staging_residue(data_dir) == []
        assert _walk_digests(hold_a) == healthy_digests

        # Remediation choreography: remove the marker, bring the slot back.
        marker_path.unlink()
        hold_a.replace(data_dir)

        # ── (b) corrupt marker self-heal: newest valid candidate wins ──
        candidate_old = _make_quarantine_candidate(
            data_dir, "cand-old", "OLD", mtime_shift=-100_000.0
        )
        candidate_new = _make_quarantine_candidate(
            data_dir, "cand-new", "NEW", mtime_shift=-1_000.0
        )
        new_digests = _walk_digests(candidate_new)
        shutil.rmtree(data_dir)  # crash window: slot absent
        corrupt_bytes = b'{"version": 1, "token": "trun'
        marker_path.write_bytes(corrupt_bytes)

        session = bootstrap.library_service.open_session(library)  # self-heals
        # The NEWEST validated candidate was auto-restored into the slot.
        assert (data_dir / "sentinel.txt").read_text(encoding="utf-8") == "NEW"
        assert _stable_digests(data_dir) == new_digests
        # Database is functional after the self-heal.
        session.connection_for().execute("SELECT 1").fetchone()
        bootstrap.library_service.close_session(session)
        # Corrupt bytes preserved in place as evidence, live marker gone.
        evidence = export_io_module.quarantined_restore_intent_marker(data_dir)
        assert evidence is not None
        assert evidence.name.startswith(marker_path.name + ".corrupt-")
        assert evidence.read_bytes() == corrupt_bytes
        assert not marker_path.exists()
        # candidate_new was consumed by the rollback; candidate_old remains.
        assert candidate_new not in _quarantine_entries(data_dir)
        assert _quarantine_entries(data_dir) == [candidate_old]

        # ── (c) corrupt marker, no candidate → fail closed, repeatedly ──
        bootstrap.library_service.close()
        bootstrap = ApplicationBootstrap()
        shutil.rmtree(data_dir)
        shutil.rmtree(candidate_old)  # no candidates left in the quarantine
        evidence.unlink()  # (c) performs its own rename-in-place
        corrupt_three = b"corrupt-marker-no-candidate"
        marker_path.write_bytes(corrupt_three)
        with pytest.raises(RuntimeError) as excinfo_c:
            bootstrap.library_service.open_session(library)
        message_c = str(excinfo_c.value)
        assert "no validated backup candidate is available" in message_c
        assert "Manual recovery" in message_c
        # Evidence kept (renamed in place, bytes preserved), slot stays
        # absent — an empty database must NOT be materialized over the loss.
        evidence_c = export_io_module.quarantined_restore_intent_marker(data_dir)
        assert evidence_c is not None
        assert evidence_c.read_bytes() == corrupt_three
        assert not marker_path.exists()
        assert not data_dir.exists()
        assert _staging_residue(data_dir) == []
        # The quarantined corrupt marker keeps later opens failing closed.
        with pytest.raises(RuntimeError, match="no validated backup candidate"):
            bootstrap.library_service.open_session(library)
        assert not data_dir.exists()
        # The status surface keeps the recovery dialog usable without a DB.
        assert bootstrap.library_service.restore_intent_status(library) == {
            "marker": str(evidence_c),
            "status": "corrupt-quarantined",
            "quarantine_entry": None,
            "token": None,
        }
    finally:
        bootstrap.library_service.close()


def test_row7_concurrent_mutex_and_token_contract(tmp_path, runtime_domain):
    library = tmp_path / "library7"
    library.mkdir()
    _write_raw_assets(library)
    expected_assets = _walk_digests(library)

    # ── Source runtime domain: seed and create the shared archive ──
    runtime_domain("source")
    bootstrap = ApplicationBootstrap()
    try:
        session = bootstrap.library_service.open_session(library)
        services = bootstrap.runtime_for(session).services
        _seed_runtime_data(services, session, session.root)
        projection_archive = _projection(session.connection_for())
        archive = tmp_path / "artifacts" / "library_backup.assetbackup.zip"
        backup_result = services.export_service.create_backup(session.root, archive)
        assert services.export_service.validate_backup(
            archive, expected_library_root=session.root
        ).valid
    finally:
        bootstrap.library_service.close()

    # ── Destination runtime domain: seed the overwrite victim state ──
    destination_runtime = runtime_domain("destination")
    bootstrap_b = ApplicationBootstrap()
    try:
        session_b = bootstrap_b.library_service.open_session(library)
        services_b = bootstrap_b.runtime_for(session_b).services
        _seed_destination_state(services_b, session_b, session_b.root)
        projection_dest = _projection(session_b.connection_for())
        data_dir = session_b.data_dir
        service_b = services_b.export_service
        bootstrap_b.library_service.close_session(session_b)
    finally:
        bootstrap_b.library_service.close()
    old_digests = _walk_digests(data_dir)
    marker_path = export_io_module.restore_intent_path(data_dir)

    # ── Round 1 child parked in the install swap: mutex contract ──
    child, barrier, child_log = _spawn_blocked_restore(
        tmp_path, "r1", library, archive, destination_runtime
    )
    bootstrap_c = ApplicationBootstrap()
    try:
        # Actual lock contract: tryLock(0) refusal — a second process fails
        # FAST with LibraryAlreadyOpenError for open, restore and the manual
        # recovery surface; nothing is queued and nothing is corrupted.
        with pytest.raises(LibraryAlreadyOpenError):
            bootstrap_c.library_service.open_session(library)
        with pytest.raises(LibraryAlreadyOpenError):
            service_b.restore_backup(archive, library, overwrite_existing=True)
        assert service_b.restore_failure_state is None  # refused, not poisoned
        with pytest.raises(LibraryAlreadyOpenError):
            bootstrap_b.library_service.retry_interrupted_restore(library)
        with pytest.raises(LibraryAlreadyOpenError):
            bootstrap_b.library_service.acknowledge_restore_intent(library, "x")
        # The status surface is a lock-free read and stays usable.
        status = bootstrap_b.library_service.restore_intent_status(library)
        assert status["status"] == "recoverable"
        marker_token = status["token"]
        assert marker_token
        quarantined_previous = Path(status["quarantine_entry"])
        assert quarantined_previous.is_dir()
        # Both sides intact: the child is still parked, the crash-window
        # evidence is unchanged, and the victim slot is still absent.
        assert child.poll() is None
        assert not data_dir.exists()
        assert marker_path.exists()
        assert _walk_digests(quarantined_previous) == old_digests

        # ── Crash window cannot be ACKed away even with the correct token ──
        _kill_blocked_restore(child)
        with pytest.raises(RuntimeError, match="verified RuntimeData directory"):
            bootstrap_b.library_service.acknowledge_restore_intent(
                library, marker_token
            )
        assert marker_path.exists()  # marker survived the rejected ACK

        # ── Round 1 recovery: startup rollback on the next open ──
        session_r = bootstrap_c.library_service.open_session(library)
        assert (data_dir / "assetmanager.db").exists()
        assert _stable_digests(data_dir) == old_digests
        assert not marker_path.exists()
        assert _quarantine_entries(data_dir) == []
        assert _projection(session_r.connection_for()) == projection_dest
        bootstrap_c.library_service.close_session(session_r)
        assert len(_staging_residue(data_dir)) == 1
    finally:
        bootstrap_c.library_service.close()

    # ── Rounds 2 and 3: same interrupted-restore/rollback cycle ──
    for round_index in (2, 3):
        child, barrier, child_log = _spawn_blocked_restore(
            tmp_path, f"r{round_index}", library, archive, destination_runtime
        )
        assert child.poll() is None and not data_dir.exists()
        _kill_blocked_restore(child)
        bootstrap_c = ApplicationBootstrap()
        try:
            session_r = bootstrap_c.library_service.open_session(library)
            assert _stable_digests(data_dir) == old_digests
            assert not marker_path.exists()
            # Rollback drains the quarantine every round: no accumulation.
            assert _quarantine_entries(data_dir) == []
            # Staging residue grows by exactly one per interrupted attempt.
            assert len(_staging_residue(data_dir)) == round_index
            bootstrap_c.library_service.close_session(session_r)
        finally:
            bootstrap_c.library_service.close()

    # ── Deterministic residue upper bound after 3 interrupted rounds ──
    residue = _staging_residue(data_dir)
    assert len(residue) == 3  # exactly one leftover per interrupted attempt
    quarantine_after_rounds = _quarantine_entries(data_dir)
    assert quarantine_after_rounds == []  # drained by every rollback

    # ── Final normal restore succeeds and bounds still hold ──
    bootstrap_d = ApplicationBootstrap()
    try:
        session_d = bootstrap_d.library_service.open_session(library)
        service_d = bootstrap_d.runtime_for(session_d).services.export_service
        bootstrap_d.library_service.close_session(session_d)
        restore_result = service_d.restore_backup(
            archive, library, overwrite_existing=True
        )
        assert restore_result.file_count == backup_result.file_count
        previous = restore_result.previous_data_dir
        assert previous is not None and _walk_digests(previous) == old_digests
        reopened = bootstrap_d.library_service.open_session(library)
        assert _projection(reopened.connection_for()) == projection_archive
        bootstrap_d.library_service.close_session(reopened)
        assert len(_staging_residue(data_dir)) == 3
        assert _quarantine_entries(data_dir) == [previous]
        assert _walk_digests(library) == expected_assets

        # ── Manual-disposal token contract (slot present, stale marker) ──
        session_t = bootstrap_d.library_service.open_session(library)
        with pytest.raises(
            RuntimeError, match="Cannot acknowledge restore intent while library is active"
        ):
            bootstrap_d.library_service.acknowledge_restore_intent(library, "x")
        with pytest.raises(
            RuntimeError, match="Cannot recover restore intent while library is active"
        ):
            bootstrap_d.library_service.retry_interrupted_restore(library)
        bootstrap_d.library_service.close_session(session_t)

        token = export_io_module.write_restore_intent(
            data_dir,
            map_key=root_identity(library).map_key,
            quarantine_entry=previous,
            staging=data_dir.parent / f".{data_dir.name}.restore-stale",
        )
        status = bootstrap_d.library_service.restore_intent_status(library)
        assert status["status"] == "recoverable"
        assert status["token"] == token
        assert status["quarantine_entry"] == str(previous)
        installed_digests = _walk_digests(data_dir)
        with pytest.raises(RuntimeError, match="stale or unknown token"):
            bootstrap_d.library_service.acknowledge_restore_intent(library, "wrong")
        assert marker_path.exists()
        bootstrap_d.library_service.acknowledge_restore_intent(library, token)
        assert not marker_path.exists()
        assert _walk_digests(data_dir) == installed_digests  # data untouched
        assert bootstrap_d.library_service.restore_intent_status(library) is None
    finally:
        bootstrap_d.library_service.close()
