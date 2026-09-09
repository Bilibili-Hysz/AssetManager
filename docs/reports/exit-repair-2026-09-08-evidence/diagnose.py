"""Run the unmodified frozen candidate with an observer in a synthetic runtime."""
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / '.pytest-tmp-lead-snapshots/final-repair-103f119/source'
run_id = sys.argv[1]
OUT = HERE / run_id
OUT.mkdir(parents=True, exist_ok=False)
os.environ['AM_EXIT_DIAGNOSTIC_LOG'] = str(OUT / 'qt-events.jsonl')
os.environ.pop('QT_QPA_PLATFORM', None)
spec = importlib.util.spec_from_file_location('exit_w6', BASE / 'scripts/perf/w6_package_functional.py')
w6 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w6)
seed = w6._seed_runtime


def seed_observed(runtime, *args, **kwargs):
    result = seed(runtime, *args, **kwargs)
    target = runtime / 'Shared/plugins/exit-observer'
    if os.environ.get('AM_EXIT_OBSERVER_DISABLE') != '1':
        shutil.copytree(HERE / 'diagnostic-plugin', target)
    (OUT / 'runtime-path.txt').write_text(str(runtime), encoding='utf-8')
    return result


def record(phase, hwnd):
    keys = {name: bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
            for name, vk in [('ctrl', 17), ('shift', 16), ('alt', 18), ('win_l', 91), ('win_r', 92), ('q', 81)]}
    item = {'phase': phase, 'time': time.time(), 'hwnd': hwnd,
            'foreground': int(ctypes.windll.user32.GetForegroundWindow() or 0),
            'maximized': bool(ctypes.windll.user32.IsZoomed(hwnd)), 'pressed': keys}
    with (OUT / 'native-input.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(item) + '\n')


original_send = w6._send_ctrl_q


def send_observed(hwnd):
    record('before_ctrl_q', hwnd)
    result = original_send(hwnd)
    record('after_ctrl_q', hwnd)
    return result


w6._seed_runtime = seed_observed
w6._send_ctrl_q = send_observed
w6.tempfile.mkdtemp = lambda **_kwargs: str(OUT / 'synthetic')
sys.argv = ['w6_package_functional.py', *sys.argv[2:]]
os.chdir(OUT)
code = w6.main()
manifest = {'candidate': sys.argv[sys.argv.index('--exe') + 1],
            'exit_code': code, 'observer_files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (HERE / 'diagnostic-plugin').glob('*') if p.is_file()},
            'w6_sha256': hashlib.sha256(Path(w6.__file__).read_bytes()).hexdigest()}
(OUT / 'diagnostic-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
raise SystemExit(code)
