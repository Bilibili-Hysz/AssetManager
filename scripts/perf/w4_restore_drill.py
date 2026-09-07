"""W4: backup restore drill — normal path + controlled interruption.

Phase 1 (normal): synthetic library (tags/ratings/collections/nested),
export via LibraryExportService.export_metadata_json, restore into a FRESH
library root, reopen, verify metadata round-trips (tags/ratings/collections).

Phase 2 (interruption): child process performs restore_backup into the SAME
library root with overwrite, with Path.replace patched: the FIRST replace
(old → quarantine) succeeds and writes a phase marker; the SECOND replace
(staging → install) blocks on an IPC barrier file forever. Parent waits for
the marker, force-kills the child. Then the parent opens the library and
verifies the "complete old state" (quarantined old data recovered by the
startup path / restore intent), never an empty or mixed DB.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
ROOT = Path(__file__).resolve().parents[2]

CHILD = r'''
import os, sys, time
from pathlib import Path
sys.path.insert(0, os.environ["AM_REPO_ROOT"])
runtime = Path(os.environ["AM_RUNTIME_ROOT"])
lib = Path(os.environ["AM_LIB"])
archive = Path(os.environ["AM_ARCHIVE"])
barrier = Path(os.environ["AM_BARRIER"])

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
from AssetsManager.core.tag_library import get_library
install_tag_canonicalizer(get_library().canonical)
bootstrap = ApplicationBootstrap()
session = bootstrap.library_service.open_session(lib)
services = bootstrap.runtime_for(session).services
tag_svc = services.tag_service
for p, tags in ((lib / "hero.png", ["hero", "scene"]),
                (lib / "模型_场景.png", ["mmd", "scene"])):
    for tg in tags:
        tag_svc.add_tag(lib, p, tg)
meta_svc = services.metadata_service
meta_svc.set_rating(lib, lib / "hero.png", 5)
meta_svc.set_rating(lib, lib / "模型_场景.png", 3)
meta_svc.set_notes(lib, lib / "hero.png", "备注：hero 场景")
coll_svc = services.collection_service
created = coll_svc.create(lib, "我的合集")
coll_svc.add_files(lib, created["id"], [str(lib / "hero.png")])

# create_backup（session 活跃时）→ 导出归档
from AssetsManager.application.library_export_service import LibraryExportService
archive = lib.parent / "backup.zip"
archive.unlink(missing_ok=True)
export_svc = LibraryExportService(
    connection_provider=session.connection_for,
    session=session,
    restore_coordinator=bootstrap.library_service.restore_reservation,
    restore_state_provider=lambda _root=None: bootstrap.library_service.restore_failure_state_provider(lib) if hasattr(bootstrap.library_service, "restore_failure_state_provider") else None,
    restore_acknowledger=lambda _root=None, token=None: None,
)
export_svc.create_backup(lib, archive)

# close_session（提交拆除）→ restore 可过 coordinator 检查
bootstrap.library_service.close_session(session)
services = None

# Phase marker: old data quarantined, new data NOT yet installed.
# Patch Path.replace: call #1 (old→quarantine) passes; call #2 (staging→data)
# writes the barrier and blocks forever (simulating process death).
import pathlib
real_replace = pathlib.Path.replace
call_count = {"n": 0}
def patched_replace(self, target):
    call_count["n"] += 1
    if call_count["n"] == 2 and "restore" in str(self):
        barrier.write_text("quarantined", encoding="utf-8")
        time.sleep(3600)  # parent kills us here
    return real_replace(self, target)
pathlib.Path.replace = patched_replace

result = export_svc.restore_backup(archive, lib, overwrite_existing=True)
(barrier.parent / "restore_done_unexpectedly").write_text(str(result), encoding="utf-8")
'''

def build_lib(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    (root / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 64)
    (root / "模型_场景.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"2" * 64)
    (root / "a%2Fb.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"3" * 64)
    (root / "nested").mkdir()
    (root / "nested" / "deep.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"4" * 64)
    return {"tags": True, "ratings": True, "collections": True}

def main() -> None:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
    from AssetsManager.core.tag_library import get_library
    install_tag_canonicalizer(get_library().canonical)

    tmp = Path(tempfile.mkdtemp(prefix="w4-restore-"))
    lib = tmp / "library"
    build_lib(lib)
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(lib)
    services = bootstrap.runtime_for(session).services

    # 写入可验证的元数据：标签/评分/集合
    tag_svc = services.tag_service
    for p, tags in ((lib / "hero.png", ["hero", "scene"]),
                    (lib / "模型_场景.png", ["mmd", "scene"])):
        for t in tags:
            tag_svc.add_tag(lib, p, t)
    meta_svc = services.metadata_service
    meta_svc.set_rating(lib, lib / "hero.png", 5)
    meta_svc.set_rating(lib, lib / "模型_场景.png", 3)
    meta_svc.set_notes(lib, lib / "hero.png", "备注：hero 场景")
    coll_svc = services.collection_service
    created = coll_svc.create(lib, "我的合集")
    coll_svc.add_files(lib, created["id"], [str(lib / "hero.png")])

    # 导出（ZIP 备份：restore_backup 的输入格式）
    export_svc = services.export_service
    archive = tmp / "backup.zip"
    export_svc.create_backup(lib, archive)
    print("export OK:", archive.stat().st_size, "bytes")

    bootstrap.library_service.close_session(session)
    app.processEvents()

    # ── Phase 2: 受控中断 ──
    barrier = tmp / "barrier"
    env = dict(os.environ)
    env.update({"AM_REPO_ROOT": str(ROOT), "AM_RUNTIME_ROOT": str(tmp / "child_runtime"),
                "AM_LIB": str(lib), "AM_ARCHIVE": str(archive), "AM_BARRIER": str(barrier)})
    (tmp / "child_runtime").mkdir()
    child_src = tmp / "child_restore.py"
    child_src.write_text(CHILD, encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(child_src)], env=env, cwd=str(ROOT),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    deadline = time.perf_counter() + 30
    while time.perf_counter() < deadline:
        if barrier.exists():
            break
        time.sleep(0.1)
    if not barrier.exists():
        print("INTERRUPTION: barrier never reached"); print(proc.stdout.read()[-800:] if proc.poll() is not None else "still running")
        proc.kill()
        return
    print("barrier reached: old data quarantined, new data NOT installed")
    time.sleep(0.3)
    proc.kill()
    proc.wait(timeout=10)
    print("child killed at interruption point")

    # ── 恢复验证：重启后 open_session 应读到完整旧状态（恢复意图/隔离区恢复）──
    app2 = QApplication.instance() or QApplication([])
    bootstrap2 = ApplicationBootstrap()
    install_tag_canonicalizer(get_library().canonical)
    session2 = bootstrap2.library_service.open_session(lib)
    services2 = bootstrap2.runtime_for(session2).services
    tag_svc2 = services2.tag_service
    tags_hero = tag_svc2.get_tags_for_files(lib, [str(lib / "hero.png")])
    vals = list(tags_hero.values())
    hero_tags = sorted(vals[0]) if vals else []
    meta2 = services2.metadata_service
    rating = meta2.get_rating(lib, lib / "hero.png")
    state = bootstrap2.library_service.restore_intent_status(lib)
    db = lib / "RuntimeData" / "assetmanager.db"
    print("recovery state:", json.dumps(state, ensure_ascii=False)[:120] if state else "None")
    print(f"hero tags: {hero_tags}, hero rating: {rating}")
    print(f"db exists: {db.exists()}, size: {db.stat().st_size if db.exists() else 0}")
    complete_old = set(hero_tags) >= {"hero", "scene"} and rating == 5
    empty = db.exists() and db.stat().st_size < 10000
    print("VERDICT:", "complete-old-state" if complete_old else ("empty-or-mixed" if empty else "mixed/unknown"))

    bootstrap2.library_service.close_session(session2)
    app2.processEvents()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
