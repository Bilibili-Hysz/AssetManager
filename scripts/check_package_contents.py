"""Validate a PyInstaller onefile or onedir bundle.

Three independent layers, all answering "is the release artifact complete?":

1. ``check_exe`` / ``check_onedir`` — structural + content verification of a
   built bundle:
   * ``check_exe`` walks the embedded CArchive TOC of a onefile
     ``AssetManager.exe`` (PE magic + size floor + every resource the spec
     ``datas`` and Qt requirements declare);
   * ``check_onedir`` walks the collected ``_internal`` tree of an onedir
     ``dist/AssetManager`` directory against the same resource contract.
   ``check_bundle`` dispatches on the path type (file -> onefile, dir -> onedir).

2. ``check_spec`` — static drift guard over ``AssetManager.spec`` (no build
   needed): every repo-source ``datas`` path exists on disk, and every
   ``AssetsManager.*`` hidden import resolves to a real module file. This is
   the guard that would have caught the 24 dead shop/order/quota/seller
   entries removed during M3.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = ROOT / "AssetManager.spec"

# ── Layer 1: embedded resource contract (single-file) ─────────────────────
# Destination paths are forward-slash normalized; the embedded CArchive TOC
# uses backslashes on Windows and is normalized before matching.
REQUIRED_DATA_FILES = (
    "webui/dist/index.html",
    "AssetsManager/i18n/en.json",
    "AssetsManager/i18n/zh.json",
    "AssetsManager/i18n/ja.json",
    "assets/icons/icon.ico",
)
REQUIRED_NONEMPTY_DIRS = (
    "webui/dist/assets/",
    "Assets/Themes/",
    "Plugins/",
)
REQUIRED_QT_MODULES = ("QtSvg", "QtOpenGL", "QtOpenGLWidgets")
REQUIRED_QT_RUNTIME_LIBRARIES = ("Qt6Svg", "Qt6OpenGL", "Qt6OpenGLWidgets")
REQUIRED_QT_BINARY_SUFFIXES = frozenset({".pyd", ".so", ".dylib"})
REQUIRED_QT_RUNTIME_SUFFIXES = frozenset({".dll", ".so", ".dylib"})

# Sanity floor well below the real ~75 MB bundle but above a bare Python
# onefile (~10-15 MB); a build that silently dropped Qt or the SPA falls
# under it, while exact resource presence is verified via the TOC check.
MIN_EXE_SIZE = 20 * 1024 * 1024

# ── Layer 2: spec drift contract ──────────────────────────────────────────
_DATAS_SOURCE_RE = re.compile(
    r"str\(\s*_root\s*/\s*((?:'[^']*'\s*/\s*)+'[^']*')\s*\)"
)


def _normalize(entry: str) -> str:
    return entry.replace("\\", "/")


def _is_pe(exe_path: Path) -> bool:
    with open(exe_path, "rb") as f:
        return f.read(2) == b"MZ"


def _has_qt_module(entries: list[str], module_name: str) -> bool:
    prefix = module_name.lower() + "."
    for entry in entries:
        name = entry.rsplit("/", 1)[-1].lower()
        if name.startswith(prefix) and any(
            name.endswith(suffix) for suffix in REQUIRED_QT_BINARY_SUFFIXES
        ):
            return True
    return False


def _has_qt_runtime(entries: list[str], library_stem: str) -> bool:
    stem = library_stem.lower()
    prefixes = (f"{stem}.", f"lib{stem}.")
    for entry in entries:
        name = entry.rsplit("/", 1)[-1].lower()
        if name.startswith(prefixes) and any(
            name.endswith(suffix) for suffix in REQUIRED_QT_RUNTIME_SUFFIXES
        ):
            return True
    return False


def check_toc(entries, *, case_insensitive: bool = False) -> list[str]:
    """Return missing embedded resources for a normalized TOC entry iterable.

    ``case_insensitive`` mirrors Windows' case-insensitive filesystem: an
    onedir bundle merges ``assets/`` and ``Assets/`` (the spec intentionally
    ships the icon under lowercase ``assets/icons`` and themes under capital
    ``Assets/Themes``), so the directory walk cannot preserve the spec's
    mixed casing the way a case-sensitive CArchive TOC does.
    """
    normalized = [_normalize(str(entry)) for entry in entries]
    if case_insensitive:
        normalized = [entry.lower() for entry in normalized]
    missing: list[str] = []
    for relative_path in REQUIRED_DATA_FILES:
        target = relative_path.lower() if case_insensitive else relative_path
        if target not in normalized:
            missing.append(relative_path)
    for prefix in REQUIRED_NONEMPTY_DIRS:
        pfx = prefix.lower() if case_insensitive else prefix
        if not any(entry.startswith(pfx) for entry in normalized):
            missing.append(f"{prefix.rstrip('/')} (no entries)")
    for module_name in REQUIRED_QT_MODULES:
        if not _has_qt_module(normalized, module_name):
            missing.append(f"PySide6/{module_name} (binary)")
    for library_stem in REQUIRED_QT_RUNTIME_LIBRARIES:
        if not _has_qt_runtime(normalized, library_stem):
            missing.append(f"PySide6/{library_stem} (runtime library)")
    return missing


def _embedded_toc(exe_path: Path) -> list[str]:
    """Return raw TOC entry names from a onefile exe (lazy PyInstaller import)."""
    from PyInstaller.archive.readers import CArchiveReader

    return [str(key) for key in CArchiveReader(str(exe_path)).toc.keys()]


def check_exe(exe_path: Path, min_size: int = MIN_EXE_SIZE) -> list[str]:
    """Return problems with a single-file bundle (empty = complete)."""
    missing: list[str] = []
    if not exe_path.is_file():
        return [f"missing executable: {exe_path}"]
    if not _is_pe(exe_path):
        missing.append("executable is not a valid PE image (missing MZ magic)")
    size = exe_path.stat().st_size
    if size < min_size:
        missing.append(
            f"executable size {size} bytes below minimum {min_size} bytes"
        )
    try:
        entries = _embedded_toc(exe_path)
    except ImportError:
        print(
            "warning: PyInstaller not importable; embedded TOC check skipped",
            file=sys.stderr,
        )
        entries = None
    except Exception as exc:  # pragma: no cover - depends on archive internals
        missing.append(f"cannot parse PyInstaller archive: {exc}")
        entries = None
    if entries is not None:
        missing.extend(check_toc(entries))
    return missing


def _onedir_entries(bundle_dir: Path) -> list[str]:
    """Return relative file paths (re the payload root) for an onedir bundle."""
    # PyInstaller 6 onedir: the payload lives in _internal next to the exe.
    # Pre-6 onedir layouts kept everything directly beside the exe.
    payload_root = bundle_dir / "_internal"
    if not payload_root.is_dir():
        payload_root = bundle_dir
    entries: list[str] = []
    for path in payload_root.rglob("*"):
        if path.is_file():
            entries.append(str(path.relative_to(payload_root)))
    return entries


def check_onedir(bundle_dir: Path) -> list[str]:
    """Return problems with an onedir bundle directory (empty = complete)."""
    problems: list[str] = []
    exe = bundle_dir / "AssetManager.exe"
    if not exe.is_file():
        return [f"missing onedir executable: {exe}"]
    if not _is_pe(exe):
        problems.append("executable is not a valid PE image (missing MZ magic)")
    entries = _onedir_entries(bundle_dir)
    if not entries:
        problems.append("onedir bundle collected no payload files")
    problems.extend(check_toc(entries, case_insensitive=True))
    return problems


def check_bundle(bundle: Path, min_size: int = MIN_EXE_SIZE) -> list[str]:
    """Check a onefile exe (path is a file) or an onedir dir (path is a dir)."""
    if bundle.is_file():
        return check_exe(bundle, min_size)
    if bundle.is_dir():
        return check_onedir(bundle)
    return [f"bundle path does not exist: {bundle}"]


def _datas_sources(spec_text: str) -> list[str]:
    sources: list[str] = []
    for match in _DATAS_SOURCE_RE.finditer(spec_text):
        parts = [part.strip().strip("'\"") for part in match.group(1).split("/")]
        sources.append("/".join(parts))
    return sources


def _assetsmanager_hiddenimports(spec_text: str) -> list[str]:
    if "hiddenimports=[" not in spec_text:
        return []
    body = spec_text.split("hiddenimports=[", 1)[1].split("]", 1)[0]
    return [
        module for module in re.findall(r"'([^']+)'", body)
        if module.startswith("AssetsManager.")
    ]


def _module_exists(module: str, root: Path) -> bool:
    rel = module[len("AssetsManager."):].replace(".", "/")
    base = root / "AssetsManager" / rel
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def check_spec(spec_path: Path = DEFAULT_SPEC) -> list[str]:
    """Return spec drift problems (empty = consistent with the source tree)."""
    if not spec_path.is_file():
        return [f"spec not found: {spec_path}"]
    text = spec_path.read_text(encoding="utf-8")
    problems: list[str] = []
    for source in _datas_sources(text):
        if source.startswith("webui/"):
            # Generated by the WebUI build; its presence in the artifact is
            # verified by the embedded TOC check instead of the source tree.
            continue
        if not (spec_path.parent / source).exists():
            problems.append(f"datas source missing: {source}")
    for module in _assetsmanager_hiddenimports(text):
        if not _module_exists(module, spec_path.parent):
            problems.append(f"hidden import not found: {module}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "bundle",
        type=Path,
        help="Path to dist/AssetManager.exe (onefile) or dist/AssetManager (onedir)",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=DEFAULT_SPEC,
        help="Path to AssetManager.spec for the static drift check",
    )
    args = parser.parse_args(argv)

    problems = check_bundle(args.bundle)
    problems.extend(check_spec(args.spec))

    if problems:
        print("Package is missing required resources:", file=sys.stderr)
        for path in problems:
            print(f"  - {path}", file=sys.stderr)
        return 1

    print(f"Package contents verified: {args.bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
