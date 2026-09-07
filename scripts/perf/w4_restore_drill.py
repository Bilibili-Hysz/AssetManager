"""W4: backup restore drill — normal path + controlled interruption.

Runtime-domain rule (weekly-review 2026-09-07, defect W4): ALL library data
(tags/ratings/collections/DB) lives under ``AM_RUNTIME_ROOT`` and every
process below shares the SAME root, so the recovery verification reads
exactly the runtime domain where the interruption happened.  The parent
process never opens the library itself — the old drill seeded data in the
parent's own default runtime and then "verified" that data, which passed
regardless of what the child's restore machinery did.

  tmp/
    library/                  synthetic library files (no RuntimeData)
    child_runtime/            THE shared AM_RUNTIME_ROOT for both children
    backup_old.zip            NEW-state  backup is backup_new.zip (see child)
    backup_new.zip            OLD-state  marker drill, see below
    phase1_ok / barrier / ... coordination markers

Interrupted child (AM_RUNTIME_ROOT=child_runtime):
  1. open_session(lib)            -> fresh DB materialized in child_runtime
  2. seed NEW state               -> hero tags ["new_tag"], rating 2
  3. create_backup -> backup_new  -> archive holds the NEW state
  4. transform to OLD state       -> hero tags ["hero","scene"], rating 5,
                                     notes, collection "我的合集"
  5. create_backup -> backup_old  -> archive holds the OLD state
  6. Phase 1 NORMAL restore: restore_backup(backup_old, overwrite=True)
     completes unpatched; reopen and verify the full round-trip.  The live
     data_dir now holds the OLD state — the "old library" for Phase 2.
  7. Patch Path.replace: the install replace (staging -> data_dir) writes
     the barrier and blocks forever.  restore_backup(backup_new) therefore
     quarantines the OLD data (replace #1) and dies before installing the
     NEW data (replace #2).  On-disk: restore-intent marker + quarantined
     OLD data + never-installed staging.

Verification child (SAME AM_RUNTIME_ROOT=child_runtime):
  open_session must run the startup recovery (_recover_interrupted_library_restore:
  install the quarantined OLD data, clear the marker) and read the complete
  OLD state — never the NEW backup content, never an empty DB.  It also
  proves the runtime domain by checking session.data_dir is inside
  AM_RUNTIME_ROOT and by using the real DB location (session.data_dir /
  "assetmanager.db" — resolved by path_resolver, NOT lib/RuntimeData/).

Any timeout, unexpected restore completion, or verdict mismatch exits
non-zero (sys.exit(1)).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
ROOT = Path(__file__).resolve().parents[2]

PHASE1_TIMEOUT = 300.0
BARRIER_TIMEOUT = 90.0
VERIFY_TIMEOUT = 300.0

CHILD = r'''
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.environ["AM_REPO_ROOT"])
lib = Path(os.environ["AM_LIB"])
backup_new = Path(os.environ["AM_BACKUP_NEW"])
backup_old = Path(os.environ["AM_BACKUP_OLD"])
barrier = Path(os.environ["AM_BARRIER"])
phase1_ok = Path(os.environ["AM_PHASE1_OK"])
done_marker = Path(os.environ["AM_RESTORE_DONE"])
error_file = Path(os.environ["AM_CHILD_ERROR"])


def fail(message: str):
    error_file.write_text(message, encoding="utf-8")
    print("CHILD-FAIL:", message, flush=True)
    sys.exit(1)


from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
from AssetsManager.core.tag_library import get_library
install_tag_canonicalizer(get_library().canonical)
bootstrap = ApplicationBootstrap()

hero = str(lib / "hero.png")
scene = str(lib / "模型_场景.png")


def seed_state(services, *, new_state: bool) -> None:
    """NEW state = distinguishable backup content; OLD state = live content."""
    tag_svc = services.tag_service
    meta_svc = services.metadata_service
    if new_state:
        tag_svc.add_tag(lib, hero, "new_tag")
        meta_svc.set_rating(lib, hero, 2)
        return
    for t in ("new_tag",):
        tag_svc.remove_tag(lib, hero, t)
    for t in ("hero", "scene"):
        tag_svc.add_tag(lib, hero, t)
    for t in ("mmd", "scene"):
        tag_svc.add_tag(lib, scene, t)
    meta_svc.set_rating(lib, hero, 5)
    meta_svc.set_rating(lib, scene, 3)
    meta_svc.set_notes(lib, hero, "备注：hero 场景")


def verify_old_state(services) -> None:
    tag_svc = services.tag_service
    meta_svc = services.metadata_service
    got = tag_svc.get_tags_for_files(lib, [hero, scene])
    # The canonicalizer may re-case tags (e.g. "mmd" -> "MMD"); compare
    # case-insensitively.
    hero_tags = {t.lower() for t in got.get(hero, [])}
    scene_tags = {t.lower() for t in got.get(scene, [])}
    rating = meta_svc.get_rating(lib, hero)
    notes = meta_svc.get_notes(lib, hero)
    if hero_tags != {"hero", "scene"} or scene_tags != {"mmd", "scene"}:
        fail(f"old-state tags wrong: hero={sorted(hero_tags)} scene={sorted(scene_tags)}")
    if rating != 5:
        fail(f"old-state rating wrong: {rating}")
    if notes != "备注：hero 场景":
        fail(f"old-state notes wrong: {notes!r}")


try:
    # ── 1-2: fresh DB in child_runtime, seed the NEW (backup) state ──
    session = bootstrap.library_service.open_session(lib)
    services = bootstrap.runtime_for(session).services
    seed_state(services, new_state=True)

    # ── 3: NEW-state archive ──
    services.export_service.create_backup(lib, backup_new)
    if not backup_new.exists():
        fail("backup_new.zip was not created")
    print("backup_new OK:", backup_new.stat().st_size, "bytes", flush=True)

    # ── 4-5: transform to the OLD state, archive it ──
    seed_state(services, new_state=False)
    coll_svc = services.collection_service
    created = coll_svc.create(lib, "我的合集")
    coll_svc.add_files(lib, created["id"], [hero])
    services.export_service.create_backup(lib, backup_old)
    if not backup_old.exists():
        fail("backup_old.zip was not created")
    print("backup_old OK:", backup_old.stat().st_size, "bytes", flush=True)
    bootstrap.library_service.close_session(session)

    # ── 6: Phase 1 NORMAL restore (unpatched) + reopen round-trip ──
    services.export_service.restore_backup(backup_old, lib, overwrite_existing=True)
    print("normal restore completed", flush=True)
    session = bootstrap.library_service.open_session(lib)
    services = bootstrap.runtime_for(session).services
    verify_old_state(services)
    colls = [c["name"] for c in services.collection_service.list_collections(lib)]
    if "我的合集" not in colls:
        fail(f"collection missing after normal restore: {colls}")
    db = session.data_dir / "assetmanager.db"
    if not db.exists() or db.stat().st_size < 10000:
        fail(f"real DB unusable after normal restore: {db}")
    print("PHASE1 normal restore OK; data_dir:", session.data_dir, flush=True)
    bootstrap.library_service.close_session(session)
    phase1_ok.write_text("ok", encoding="utf-8")

    # ── 7: arm the interruption, then restore the NEW archive over OLD ──
    from AssetsManager.application.library_export_service import library_data_dir

    data_dir = library_data_dir(lib)
    import pathlib

    real_replace = pathlib.Path.replace

    def patched_replace(self, target):
        # Install step only: staging (".<slot>.restore-<uuid>") -> data_dir.
        if str(target) == str(data_dir) and self.name.startswith("." + data_dir.name + ".restore-"):
            barrier.write_text("install-blocked", encoding="utf-8")
            print("BARRIER: install replace blocked", flush=True)
            time.sleep(3600)  # parent force-kills us here
        return real_replace(self, target)

    pathlib.Path.replace = patched_replace
    result = services.export_service.restore_backup(backup_new, lib, overwrite_existing=True)
    # Interrupted restore must never complete.
    done_marker.write_text(json.dumps(str(result), ensure_ascii=False), encoding="utf-8")
    fail("restore completed although the install replace was patched to block")
except SystemExit:
    raise
except BaseException as exc:  # noqa: BLE001 — diagnostics go to the parent
    import traceback

    fail("child exception: " + "".join(traceback.format_exception(exc))[-1500:])
'''

VERIFY = r'''
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["AM_REPO_ROOT"])
runtime = Path(os.environ["AM_RUNTIME_ROOT"])
lib = Path(os.environ["AM_LIB"])

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
from AssetsManager.core.tag_library import get_library
install_tag_canonicalizer(get_library().canonical)
bootstrap = ApplicationBootstrap()

hero = str(lib / "hero.png")
session = bootstrap.library_service.open_session(lib)
services = bootstrap.runtime_for(session).services
data_dir = session.data_dir
db = data_dir / "assetmanager.db"

# Runtime-domain proof: the recovered slot must live in the SHARED child
# runtime (AM_RUNTIME_ROOT), not in the parent's default runtime.
domain_ok = data_dir.resolve().is_relative_to(runtime.resolve())

got = services.tag_service.get_tags_for_files(lib, [hero])
hero_tags = sorted(got.get(hero, []))
rating = services.metadata_service.get_rating(lib, hero)
notes = services.metadata_service.get_notes(lib, hero)
colls = [c["name"] for c in services.collection_service.list_collections(lib)]
intent_after = bootstrap.library_service.restore_intent_status(lib)

print("data_dir:", data_dir, flush=True)
print("runtime_domain_ok:", domain_ok, flush=True)
print("hero_tags:", hero_tags, flush=True)
print("hero_rating:", rating, flush=True)
print("hero_notes:", notes, flush=True)
print("collections:", colls, flush=True)
print("db:", db, db.exists() and db.stat().st_size, flush=True)
print("restore_intent_after_open:", intent_after, flush=True)

tags_lower = {t.lower() for t in hero_tags}
complete_old = (
    domain_ok
    and {"hero", "scene"} <= tags_lower
    and "new_tag" not in tags_lower
    and rating == 5
    and notes == "备注：hero 场景"
    and "我的合集" in colls
    and db.exists()
    and db.stat().st_size >= 10000
    and intent_after is None
)
new_state = "new_tag" in tags_lower
if complete_old:
    print("VERDICT: complete-old-state", flush=True)
    code = 0
else:
    print("VERDICT:", "new-state-installed" if new_state else "empty-or-mixed", flush=True)
    code = 1
bootstrap.library_service.close_session(session)
sys.exit(code)
'''


def build_lib(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 64)
    (root / "模型_场景.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"2" * 64)
    (root / "a%2Fb.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"3" * 64)
    nested = root / "nested"
    nested.mkdir()
    (nested / "deep.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"4" * 64)


def _wait_for(marker: Path, proc: subprocess.Popen, timeout: float) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if marker.exists():
            return True
        if proc.poll() is not None:
            return marker.exists()
        time.sleep(0.1)
    return marker.exists()


def _dump_child(proc: subprocess.Popen) -> None:
    try:
        out, _ = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate(timeout=10)
    if out:
        print("--- child output tail ---")
        print(out[-2000:])


def main() -> int:
    # Encoding contract (weekly-recheck 2026-09-08 R3): on a default-GBK
    # Windows console this drill prints child output that may contain
    # U+FFFD/Chinese, and a GBK-redirected stdout raises UnicodeEncodeError
    # mid-verdict.  Force UTF-8 on the parent's own streams and on every
    # child process so both ends of the pipe agree regardless of codepage.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")

    tmp = Path(tempfile.mkdtemp(prefix="w4-restore-"))
    try:
        return _run(tmp)
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def _run(tmp: Path) -> int:
    lib = tmp / "library"
    build_lib(lib)
    child_runtime = tmp / "child_runtime"
    child_runtime.mkdir()
    markers = {
        "AM_PHASE1_OK": tmp / "phase1_ok",
        "AM_BARRIER": tmp / "barrier",
        "AM_CHILD_ERROR": tmp / "child_error",
        "AM_RESTORE_DONE": tmp / "restore_done_unexpectedly",
    }
    env = dict(os.environ)
    env.update({
        "AM_REPO_ROOT": str(ROOT),
        # ONE runtime domain shared by the interrupted child AND the
        # verification child — the fix for defect W4.
        "AM_RUNTIME_ROOT": str(child_runtime),
        "AM_LIB": str(lib),
        "AM_BACKUP_NEW": str(tmp / "backup_new.zip"),
        "AM_BACKUP_OLD": str(tmp / "backup_old.zip"),
        # Children must emit UTF-8 even when the parent console is GBK; the
        # parent decodes with encoding="utf-8" below.
        "PYTHONIOENCODING": "utf-8",
        **{k: str(v) for k, v in markers.items()},
    })

    # ── interrupted child: Phase 1 normal restore, then Phase 2 kill ──
    child_src = tmp / "child_restore.py"
    child_src.write_text(CHILD, encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(child_src)], env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace",
    )

    if not _wait_for(markers["AM_PHASE1_OK"], proc, PHASE1_TIMEOUT):
        print("FAIL: Phase 1 (normal export -> restore -> reopen) never completed")
        if markers["AM_CHILD_ERROR"].exists():
            print("child error:", markers["AM_CHILD_ERROR"].read_text(encoding="utf-8"))
        _dump_child(proc)
        return 1
    print("Phase 1 (normal export -> restore -> reopen -> verify): OK")

    if not _wait_for(markers["AM_BARRIER"], proc, BARRIER_TIMEOUT):
        print("FAIL: interruption barrier never reached within timeout")
        if markers["AM_CHILD_ERROR"].exists():
            print("child error:", markers["AM_CHILD_ERROR"].read_text(encoding="utf-8"))
        if markers["AM_RESTORE_DONE"].exists():
            print("restore completed unexpectedly:", markers["AM_RESTORE_DONE"].read_text(encoding="utf-8"))
        _dump_child(proc)
        return 1
    print("barrier reached: OLD data quarantined, NEW data not installed")
    time.sleep(0.3)
    proc.kill()
    proc.wait(timeout=15)
    print("child killed at the interruption point (install replace)")

    if markers["AM_RESTORE_DONE"].exists():
        print("FAIL: restore completed although it should have been interrupted")
        return 1

    # ── verification child: SAME AM_RUNTIME_ROOT, fresh process ──
    verify_src = tmp / "child_verify.py"
    verify_src.write_text(VERIFY, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(verify_src)], env=env, cwd=str(ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=VERIFY_TIMEOUT,
    )
    print("--- verification child output ---")
    print(completed.stdout)
    if completed.stderr:
        print("--- verification child stderr (tail) ---")
        print(completed.stderr[-1500:])
    verdict = next(
        (line.split(":", 1)[1].strip() for line in completed.stdout.splitlines()
         if line.startswith("VERDICT:")),
        "missing",
    )
    if completed.returncode != 0 or verdict != "complete-old-state":
        print(f"FAIL: verification verdict={verdict!r} returncode={completed.returncode}")
        return 1
    print("W4 RESTORE DRILL: PASS — recovery restored the complete OLD state "
          "from the interrupted child's runtime domain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
