"""Build script — clean, build, report for PyInstaller single-file packaging."""
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'
EXE = DIST / 'AssetManager.exe'
BUILD = ROOT / 'build'
WEBUI = ROOT / 'webui'


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


def report():
    if not EXE.is_file():
        print('Build output not found.')
        return
    print(f'Output: {EXE}')
    print(f'Size: {EXE.stat().st_size / (1024 * 1024):.1f} MB')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--clean', action='store_true')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--skip-webui', action='store_true',
                        help='Skip the webui/dist SPA build (use a prebuilt one).')
    args = parser.parse_args()
    if args.clean or (not args.build and not args.report):
        clean()
    if args.build or (not args.clean and not args.report):
        build(skip_webui=args.skip_webui)
    if args.report or (not args.clean and not args.build):
        report()
