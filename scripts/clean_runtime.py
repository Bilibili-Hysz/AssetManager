#!/usr/bin/env python3
"""清理本地检出中的运行时/构建垃圾。

用法:
    python scripts/clean_runtime.py            # 干跑:列出将删除项(默认)
    python scripts/clean_runtime.py --apply    # 实际删除

守卫原则(双保险):
* 白名单模式:只处理下列清单内的产物类型,绝不执行全量 git clean;
* git-ignore 守卫:每个候选路径必须先通过 `git check-ignore`,被跟踪
  文件一律跳过并计数报告;
* 显式排除 .git/ 与 .worktrees/(后者整体被忽略,但属于其他工作树,
  其缓存由对应检出自行管理)。

刻意保留、绝不清除:
* 用户/运行时数据:RuntimeData/、artifacts/(性能趋势证据)、mirror/(历史镜像)
* 本地工具链:.agents/ .codex/ .zcode/ .cython-nuitka/(Cython/Nuitka 构建工具,已跟踪)
* 其他工作树:.worktrees/
* 依赖与下载物:node_modules/ webui/node_modules/、cloudflared-windows-amd64.exe
* vendored 构建:.gitignore 对 webui/previewer-dist/**/*.map 与 samples/ 的忽略
  属刻意设计,脚本不涉及该目录。

新增产物类型时,在 CANDIDATE_* 常量中加入即可;守卫会保证只删忽略项。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 目录名级匹配(任意深度,除非位于 exclude 根之下)
CANDIDATE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".pyright",
    "htmlcov",
    "coverage",
}

# 根级相对的目录/文件(相对 REPO_ROOT 的路径,支持 glob)
CANDIDATE_ROOT_PATTERNS = {
    "tmp",
    "build",
    "dist",
    ".pytest-*",  # 历史 pytest basetemp(.pytest-tmp-*、.pytest-thumb-*、.pytest_cache 均命中)
    "crash.log",
    "pytest-run.log",
    "pytest-full*.log",
    "crash_*.txt",
    "full_crash_output*.txt",
    "first_half.txt",
    "root_crash_new.txt",
    "test_order.txt",
}

# webui 侧构建/测试产物
CANDIDATE_WEBUI_PATTERNS = {
    "dist",
    ".vite",
    "test-results",
    "playwright-report",
    "tsconfig.tsbuildinfo",
    "artifacts",
    "coverage",
}

# Cython 生成的扩展源码(可经由 setup_cython.py 重建)
CANDIDATE_CYTHON_SOURCES = {
    "AssetsManager/application/asset_filters.c",
    "AssetsManager/core/cache.c",
    "AssetsManager/core/color_utils.c",
    "AssetsManager/core/format_utils.c",
}

# RuntimeData 下的测试残留目录前缀(由 pytest conftest fixtures 创建,
# 见 tests/conftest.py 的 opened_session 等)。真实用户资产库从不使用
# 这些前缀 —— 但为稳妥,该扫描仅在 --test-runtime 显式开启时执行,
# 且 Shared/、_orphaned/(恢复隔离区)永远保留。
TEST_RUNTIME_PREFIXES = (
    "library_", "library-", "library-a_", "library-b_",
    "second_", "untouched_", "recursive_", "MiXeDLibrary_",
    "root_", "root-a_", "root-b_", "old_", "other_",
)
TEST_RUNTIME_ALWAYS_KEEP = {"Shared", "_orphaned"}

# 明确排除的根目录(即使被 git 忽略也不动)
EXCLUDE_ROOTS = {".git", ".worktrees"}


def is_ignored(path: Path) -> bool:
    """路径必须被 git 视为 ignored 才允许删除。"""
    proc = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(path)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.returncode == 0


def excluded(path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return True
    parts = rel.parts
    if not parts:
        return False  # 路径本身就是仓库根
    return parts[0] in EXCLUDE_ROOTS


def dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def collect(include_test_runtime: bool = False) -> tuple[list[Path], int]:
    candidates: list[Path] = []

    # 1) 任意深度目录名匹配
    for root, dirs, _files in os.walk(REPO_ROOT):
        root_path = Path(root)
        if excluded(root_path):
            dirs[:] = []
            continue
        keep: list[str] = []
        for d in dirs:
            candidate = root_path / d
            if d in CANDIDATE_DIR_NAMES and not excluded(candidate):
                candidates.append(candidate)
            else:
                keep.append(d)
        dirs[:] = keep

    # 2) 根级与 webui 级相对模式
    for pattern in CANDIDATE_ROOT_PATTERNS:
        candidates.extend(p for p in REPO_ROOT.glob(pattern) if not excluded(p))
    for pattern in CANDIDATE_WEBUI_PATTERNS:
        candidates.extend(p for p in (REPO_ROOT / "webui").glob(pattern) if not excluded(p))

    # 2b) RuntimeData 测试残留(仅 --test-runtime 开启)。
    #     Shared/ 配置与真实资产库(如 "Avatars（角色）_*")永远保留。
    if include_test_runtime:
        runtime = REPO_ROOT / "RuntimeData"
        if runtime.is_dir():
            for entry in sorted(runtime.iterdir()):
                if entry.name in TEST_RUNTIME_ALWAYS_KEEP or not entry.is_dir():
                    continue
                if entry.name.startswith(TEST_RUNTIME_PREFIXES):
                    candidates.append(entry)

    # 3) Cython 生成的扩展源码
    candidates.extend(REPO_ROOT / p for p in CANDIDATE_CYTHON_SOURCES)

    # 去重 + 存在性 + git-ignore 守卫
    seen: set[Path] = set()
    kept: list[Path] = []
    skipped_tracked = 0
    for c in candidates:
        if not c.exists():
            continue  # 可能已被删/尚未生成
        resolved = c.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if is_ignored(c):
            kept.append(c)
        else:
            skipped_tracked += 1
    return kept, skipped_tracked


def main() -> int:
    parser = argparse.ArgumentParser(description="清理运行时/构建垃圾(白名单 + git-ignore 守卫)")
    parser.add_argument("--apply", action="store_true", help="实际删除;默认仅干跑")
    parser.add_argument(
        "--test-runtime",
        action="store_true",
        help="额外清理 RuntimeData/ 下的测试残留目录(库/并发/导入 fixture 产物);"
        "Shared/ 与真实资产库(如 Avatars)永远保留。默认关闭——判定是启发式的",
    )
    args = parser.parse_args()

    targets, skipped_tracked = collect(include_test_runtime=args.test_runtime)
    if not targets:
        print("无垃圾可清理 —— 检出已干净。")
        return 0

    total_bytes = 0
    for t in targets:
        size = dir_size(t) if t.is_dir() else t.stat().st_size
        total_bytes += size
        print(f"{'[del]' if args.apply else '[dry]'} {t.relative_to(REPO_ROOT)}  ({size / 1024:.0f} KB)")

    if skipped_tracked:
        print(f"跳过 {skipped_tracked} 个被跟踪/未忽略路径(守卫拦截)。")
    print(f"共 {len(targets)} 项,约 {total_bytes / 1048576:.1f} MB。")

    if args.apply:
        for t in targets:
            if t.is_dir():
                shutil.rmtree(t, ignore_errors=True)
            else:
                t.unlink(missing_ok=True)
        print("已删除。")
    else:
        print("干跑模式:加 --apply 实际删除。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())