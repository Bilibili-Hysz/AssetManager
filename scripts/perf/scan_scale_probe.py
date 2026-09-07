"""Scale-linearity probe (performance audit P2): scan/search/tags vs size.

Usage: python scripts/perf/scan_scale_probe.py
Builds 1k/5k/10k-file libraries (100 dirs × N files + nested subdirs),
measures full-scan time, indexed search latency (warmed median of 20),
and batch tag reads. Linear growth = time roughly ∝ file count.
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def build_library(root: Path, total: int) -> None:
    # 平铺 N 文件于库根：FileListPanel 是单层目录浏览，列表扫描的规模
    # 变量 = 该层条目数（与门禁基线 DIRECTORY_LIST_* 同口径）。
    for j in range(total):
        (root / f"asset_{j:05d}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 128)
    (root / "nested").mkdir(exist_ok=True)
    (root / "nested" / "readme.txt").write_bytes(b"nested")


def probe(total: int) -> dict:
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    root = Path(tempfile.mkdtemp(prefix=f"perf-scale-{total}-"))
    build_library(root, total)
    out: dict = {"files": total}
    bootstrap = ApplicationBootstrap()
    from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
    from AssetsManager.core.tag_library import get_library
    install_tag_canonicalizer(get_library().canonical)  # app.py:180 启动接缝
    session = bootstrap.library_service.open_session(root)
    services = bootstrap.runtime_for(session).services

    t0 = time.perf_counter()
    from AssetsManager.panels.file_list import FileListPanel
    panel = FileListPanel()
    panel.set_scoped_services(services)
    panel.navigate_to(str(root), set_root=True)
    panel._model._wait_for_scan()
    out["scan_s"] = time.perf_counter() - t0
    out["rows"] = len(getattr(panel._model, "_entries", []) or [])

    # 索引搜索延迟（warmed，20 次中位）
    index = services.asset_index_service
    if index is not None:
        lat = []
        for _ in range(20):
            t = time.perf_counter()
            try:
                index.search_structured(root, name_substring="asset_00")
            except TypeError:
                conn = session.connection_for(root)
                index.search_structured(conn, root, name_substring="asset_00")
            lat.append(time.perf_counter() - t)
        out["search_med_ms"] = round(statistics.median(lat) * 1000, 2)

    # 批量标签读取（先给 100 个文件打标）
    tag_svc = services.tag_service
    targets = sorted(str(p) for p in root.glob("asset_0000?.png"))[:100]
    for p in targets:
        tag_svc.add_tag(root, p, "hero")
    t = time.perf_counter()
    tag_svc.get_tags_for_files(root, targets)
    out["batch_tags_100_ms"] = round((time.perf_counter() - t) * 1000, 2)

    panel.shutdown()
    bootstrap.library_service.close_session(session)
    import shutil
    shutil.rmtree(root, ignore_errors=True)
    return out


def main() -> None:
    from PySide6.QtWidgets import QApplication  # noqa: F401 — 建立平台插件上下文
    rows = [probe(n) for n in (1000, 5000, 10000)]
    print(f"{'files':>6} {'rows':>6} {'scan_s':>8} {'search_med_ms':>14} {'batch_tags_100_ms':>18}")
    for r in rows:
        print(f"{r['files']:>6} {r.get('rows', 0):>6} {r.get('scan_s', 0):>8.3f} "
              f"{r.get('search_med_ms', 0):>14.2f} {r.get('batch_tags_100_ms', 0):>18.2f}")
    s = [r["scan_s"] for r in rows]
    if s[0] > 0:
        print(f"线性度: 5k/1k = {s[1]/s[0]:.2f}x, 10k/1k = {s[2]/s[0]:.2f}x (理想 5.0/10.0)")


if __name__ == "__main__":
    main()
