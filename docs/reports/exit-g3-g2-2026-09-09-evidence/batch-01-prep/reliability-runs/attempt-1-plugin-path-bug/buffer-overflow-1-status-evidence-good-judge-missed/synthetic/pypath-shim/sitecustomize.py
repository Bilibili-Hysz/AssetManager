import tempfile as _t
import shutil as _sh
import os as _o
from pathlib import Path as _P
_real = _t.mkdtemp
_PLUGIN_SRC = r'D:/~Vibe-Coding/Projects/AssetsManager_old-bak/.pytest-tmp-lead-snapshots/g3-ops/docs/reports/exit-g3-g2-2026-09-09-evidence/batch-01-prep/observer-plugin'
def _mk(prefix=None, suffix='', dir=None, **kw):
    if prefix and str(prefix).startswith('w6-func-'):
        d = _P(r'D:/~Vibe-Coding/Projects/AssetsManager_old-bak/.pytest-tmp-lead-snapshots/g3-ops/docs/reports/exit-g3-g2-2026-09-09-evidence/batch-01-prep/reliability-runs/buffer-overflow/synthetic') / 'synthetic'
        shared = d / 'runtime' / 'Shared'
        _o.makedirs(shared / 'plugins', exist_ok=True)
        # install the observer plugin at mkdtemp-redirect time,
        # strictly before the driver Popen's the exe
        _sh.copytree(_PLUGIN_SRC, shared / 'plugins' / 'exit-observer', dirs_exist_ok=True)

        _sh.copytree(r'D:/~Vibe-Coding/Projects/AssetsManager_old-bak/.pytest-tmp-lead-snapshots/g3-ops/docs/reports/exit-g3-g2-2026-09-09-evidence/batch-01-prep/reliability-runs/buffer-overflow/hang-plugin', shared / 'plugins' / r'amg3-hang-after-q', dirs_exist_ok=True)
        return d
    return _real(prefix=prefix, suffix=suffix, dir=dir, **kw)
_t.mkdtemp = _mk
