"""Build script — clean, build, optimize, report for PyInstaller packaging."""
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist' / 'AssetManager'
BUILD = ROOT / 'build'
WEBUI = ROOT / 'webui'

KEEP_TRANSLATIONS = {'qtbase_en.qm', 'qtbase_zh_CN.qm', 'qtbase_zh_TW.qm', 'qtbase_ja.qm'}


def clean():
    for d in (DIST.parent, BUILD):
        if d.exists():
            shutil.rmtree(d)


def webui_build(skip: bool = False):
    """Build the React/Vite SPA into webui/dist.

    AssetManager.spec bundles webui/dist as datas and the LAN server serves
    it (AssetsManager/lan/routes/pages.py SPA_DIR), so a missing build breaks
    both packaging and LAN sharing. Mirrors the CI ordering in
    .github/workflows/release.yml ('Build WebUI' before the PyInstaller step).
    """
    if skip:
        return
    if not (WEBUI / 'package.json').is_file():
        print('webui/ not present; skipping SPA build.')
        return
    if not shutil.which('npm'):
        sys.exit('npm not found on PATH; cannot build the WebUI SPA. '
                 'Install Node.js, or pass --skip-webui with a prebuilt webui/dist.')
    subprocess.run(['npm', 'ci'], cwd=str(WEBUI), check=True)
    subprocess.run(['npm', 'run', 'build'], cwd=str(WEBUI), check=True)


def build(skip_webui: bool = False):
    webui_build(skip_webui)
    result = subprocess.run(
        [sys.executable, '-m', 'PyInstaller', 'AssetManager.spec', '--noconfirm'],
        cwd=str(ROOT), capture_output=False)
    if result.returncode != 0:
        sys.exit(result.returncode)


def optimize():
    """Remove unused files from dist to reduce size."""
    if not DIST.exists():
        return
    saved = 0
    # Remove unused Qt translations
    trans_dir = DIST / '_internal' / 'PySide6' / 'translations'
    if trans_dir.is_dir():
        for f in trans_dir.iterdir():
            if f.suffix == '.qm' and f.name not in KEEP_TRANSLATIONS:
                saved += f.stat().st_size
                f.unlink()
    # Remove opengl32sw.dll (software OpenGL fallback)
    opengl = DIST / '_internal' / 'PySide6' / 'opengl32sw.dll'
    if opengl.is_file():
        saved += opengl.stat().st_size
        opengl.unlink()
    # Remove unused Qt DLLs
    for name in ('Qt6Quick.dll', 'Qt6Qml.dll', 'Qt6Pdf.dll', 'Qt6OpenGL.dll',
                 'Qt6QmlModels.dll', 'Qt6QmlWorkerScript.dll'):
        dll = DIST / '_internal' / 'PySide6' / name
        if dll.is_file():
            saved += dll.stat().st_size
            dll.unlink()
    if saved:
        print(f'Optimized: removed {saved / (1024 * 1024):.1f} MB of unused files')


def report():
    if not DIST.exists():
        print('Build output not found.')
        return
    files = list(DIST.rglob('*'))
    total = sum(f.stat().st_size for f in files if f.is_file())
    print(f'Output: {DIST}')
    print(f'Files: {len(files)}')
    print(f'Size: {total / (1024 * 1024):.1f} MB')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--clean', action='store_true')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--optimize', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--skip-webui', action='store_true',
                        help='Skip the webui/dist SPA build (use a prebuilt one).')
    args = parser.parse_args()
    if args.clean or (not args.build and not args.report and not args.optimize):
        clean()
    if args.build or (not args.clean and not args.report and not args.optimize):
        build(skip_webui=args.skip_webui)
    if args.optimize or (not args.clean and not args.build and not args.report):
        optimize()
    if args.report or (not args.clean and not args.build and not args.optimize):
        report()
