"""DB write-gate concurrency probe (performance audit P2).

Compares N threads × M tag-adds through the connection-level write gate
against the serial equivalent. >3x amplification = contention flag.
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def run(threads: int, per_thread: int) -> float:
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
    from AssetsManager.core.tag_library import get_library
    install_tag_canonicalizer(get_library().canonical)

    root = Path(tempfile.mkdtemp(prefix="perf-wlock-"))
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(root)
    services = bootstrap.runtime_for(session).services
    tag_svc = services.tag_service
    files = [str(root / f"f_{i:04d}.png") for i in range(threads * per_thread)]
    for f in files:
        (root / Path(f).name).write_bytes(b"x")

    def work(tid: int) -> None:
        mine = files[tid * per_thread:(tid + 1) * per_thread]
        for i, p in enumerate(mine):
            tag_svc.add_tag(root, p, f"tag_{tid}_{i}")

    t0 = time.perf_counter()
    if threads == 1:
        work(0)
    else:
        ts = [threading.Thread(target=work, args=(t,)) for t in range(threads)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    elapsed = time.perf_counter() - t0
    bootstrap.library_service.close_session(session)
    import shutil
    shutil.rmtree(root, ignore_errors=True)
    return elapsed


def main() -> None:
    per = 50
    serial = run(1, per)
    par = run(4, per)
    total_ops = 4 * per
    print(f"serial 100 adds: {serial:.2f}s ({serial/100*1000:.1f} ms/op)")
    print(f"4-thread 200 adds: {par:.2f}s ({par/total_ops*1000:.1f} ms/op)")
    print(f"并发放大（每 op 耗时比）: {par/total_ops/(serial/100):.2f}x（>3x = 竞争标记）")


if __name__ == "__main__":
    main()
