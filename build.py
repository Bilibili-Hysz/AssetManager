"""Build script — clean, build, report for PyInstaller onefile + onedir packaging.

Both bundle shapes are produced from the single AssetManager.spec:
  * onefile — a self-extracting ``dist/AssetManager.exe``.
  * onedir  — ``dist/AssetManager/`` (exe beside PyInstaller 6 ``_internal``).
The spec selects the shape via the AM_BUNDLE_MODE env var (see AssetManager.spec);
this script drives one PyInstaller run per requested mode.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'
BUILD = ROOT / 'build'
WEBUI = ROOT / 'webui'

# onefile product: dist/AssetManager.exe
ONEFILE_EXE = DIST / 'AssetManager.exe'
# onedir product: dist/AssetManager/AssetManager.exe (+ _internal/)
ONEDIR_EXE = DIST / 'AssetManager' / 'AssetManager.exe'

BUNDLE_MODES = ('onefile', 'onedir', 'both')


def clean():
    for d in (DIST, BUILD):
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
    # npm ships as npm.cmd on Windows; shutil.which() resolves it via PATHEXT
    # but a bare 'npm' in a list arg would not be found by CreateProcess.
    npm = shutil.which('npm')
    if not npm:
        sys.exit('npm not found on PATH; cannot build the WebUI SPA. '
                 'Install Node.js, or pass --skip-webui with a prebuilt webui/dist.')
    subprocess.run([npm, 'ci'], cwd=str(WEBUI), check=True)
    subprocess.run([npm, 'run', 'build'], cwd=str(WEBUI), check=True)


def _run_pyinstaller(bundle_mode: str):
    env = os.environ.copy()
    env['AM_BUNDLE_MODE'] = bundle_mode
    result = subprocess.run(
        [sys.executable, '-m', 'PyInstaller', 'AssetManager.spec', '--noconfirm'],
        cwd=str(ROOT), env=env, capture_output=False)
    if result.returncode != 0:
        sys.exit(result.returncode)


def build(bundle_modes, skip_webui: bool = False):
    """Build the SPA once, then run PyInstaller for each requested mode."""
    webui_build(skip_webui)
    for mode in bundle_modes:
        print(f'=== PyInstaller ({mode}) ===')
        _run_pyinstaller(mode)


def report():
    if ONEFILE_EXE.is_file():
        size = ONEFILE_EXE.stat().st_size / (1024 * 1024)
        print(f'onefile: {ONEFILE_EXE}  ({size:.1f} MB)')
    else:
        print('onefile output not found.')
    if ONEDIR_EXE.is_file():
        total = sum(
            p.stat().st_size for p in ONEDIR_EXE.parent.rglob('*') if p.is_file()
        ) / (1024 * 1024)
        print(f'onedir:  {ONEDIR_EXE.parent}  ({total:.1f} MB total)')
    else:
        print('onedir output not found.')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--clean', action='store_true')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--mode', choices=BUNDLE_MODES, default='both',
                        help='Bundle mode(s) to build (default: both).')
    parser.add_argument('--skip-webui', action='store_true',
                        help='Skip the webui/dist SPA build (use a prebuilt one).')
    args = parser.parse_args()
    if args.clean or (not args.build and not args.report):
        clean()
    if args.build or (not args.clean and not args.report):
        modes = [m for m in ('onefile', 'onedir') if args.mode in (m, 'both')]
        build(modes, skip_webui=args.skip_webui)
    if args.report or (not args.clean and not args.build):
        report()
