import tempfile as _t, sys as _s
_real = _t.mkdtemp
def _mk(prefix=None, suffix='', dir=None, **kw):
    try:
        if prefix and str(prefix).startswith('w6-func-'):
            import os as _o; d = r'D:/~Vibe-Coding/Projects/AssetsManager_old-bak/.pytest-tmp-lead-snapshots/g3-ops/docs/reports/exit-g3-g2-2026-09-09-evidence/batch-01-prep/reliability-runs/normal-exit/synthetic/synthetic'
            _o.makedirs(d, exist_ok=True)
            return d
    except Exception:
        pass
    return _real(prefix=prefix, suffix=suffix, dir=dir, **kw)
_t.mkdtemp = _mk
