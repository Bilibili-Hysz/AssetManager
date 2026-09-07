"""Adversarial stress: the three clean-boundary guards under real worker load.

Permanent keeper (self-review 2026-09-08): collection/tag/metadata mutations
must NEVER be spuriously rejected by the reconciliation worker's short
transactions on the shared connection.  File churn between rounds keeps the
real reconciliation worker busy, maximizing race windows.  50 rounds; any
"clean transaction boundary" rejection is a failure.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AM_RUNTIME_ROOT"] = tempfile.mkdtemp(prefix="guard-stress-runtime-")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from AssetsManager.application.bootstrap import ApplicationBootstrap  # noqa: E402
from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer  # noqa: E402
from AssetsManager.core.tag_library import get_library  # noqa: E402

install_tag_canonicalizer(get_library().canonical)

# 库目录必须在运行域之外：运行域卫生会清理域内的陌生目录（W3/W5/W6 探针同约定）
tmp = Path(tempfile.mkdtemp(prefix="guard-stress-lib-"))
lib = tmp / "library"
lib.mkdir()
for i in range(30):
    (lib / f"stress_{i:03d}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + os.urandom(64))

bootstrap = ApplicationBootstrap()
session = bootstrap.library_service.open_session(lib)
runtime = bootstrap.runtime_for(session)
services = runtime.services
collection = services.collection_service
tag = services.tag_service
meta = services.metadata_service

recon = services.reconciliation_service
running = bool(recon.is_running()) if callable(getattr(recon, "is_running", None)) else bool(getattr(recon, "is_running", False))
if not running and hasattr(recon, "start"):
    started = recon.start()
    running = bool(recon.is_running()) if callable(getattr(recon, "is_running", None)) else running
print(f"reconciliation worker running: {running} (started_on_demand={not running and bool(locals().get('started'))})")

ROUNDS = int(os.environ.get("GUARD_STRESS_ROUNDS", "50"))  # 每轮 7 类变更 + 文件扰动
rejections: list[str] = []
other_errors: list[str] = []
t0 = time.perf_counter()
created_ids: list[int] = []
for round_no in range(1, ROUNDS + 1):
    churn = lib / f"stress_{round_no % 30:03d}.png"
    try:
        # 文件扰动 → 对账队列 → worker 真实事务与前台变更竞争
        churn.write_bytes(b"\x89PNG\r\n\x1a\n" + os.urandom(96))
        cid = collection.create(lib, f"stress_{round_no}")["id"]
        created_ids.append(cid)
        collection.add_files(lib, cid, [churn])
        tag.add_tag(lib, churn, f"tag_{round_no}")
        meta.set_notes(lib, churn, f"note {round_no}")
        meta.set_rating(lib, churn, round_no % 6)
        meta.add_url(lib, churn, f"https://example.com/{round_no}")
        sid = collection.create_smart(lib, f"smart_{round_no}", {"extensions": [".png"]})["id"]
        collection.evaluate_count(lib, sid)
        collection.delete(lib, sid)
    except RuntimeError as exc:
        if "clean transaction boundary" in str(exc):
            rejections.append(f"round {round_no}: {exc}")
        else:
            other_errors.append(f"round {round_no}: {exc!r}")
    except Exception as exc:
        other_errors.append(f"round {round_no}: {type(exc).__name__}: {exc}")
elapsed = time.perf_counter() - t0

for cid in created_ids:
    try:
        collection.delete(lib, cid)
    except Exception as exc:
        other_errors.append(f"cleanup {cid}: {exc!r}")

print(f"rounds: {ROUNDS} in {elapsed:.1f}s")
print(f"spurious rejections: {len(rejections)}")
for r in rejections[:5]:
    print("  -", r)
print(f"other errors: {len(other_errors)}")
for r in other_errors[:5]:
    print("  -", r)
print("GUARD STRESS:", "PASS" if not rejections and not other_errors else "FAIL")

bootstrap.library_service.close()
sys.exit(0 if not rejections and not other_errors else 1)
