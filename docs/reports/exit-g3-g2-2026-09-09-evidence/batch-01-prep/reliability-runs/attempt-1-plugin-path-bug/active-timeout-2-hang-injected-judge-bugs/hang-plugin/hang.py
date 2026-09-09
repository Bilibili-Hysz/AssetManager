"""Reliability-only: hang the GUI thread after request_exit."""
from __future__ import annotations

import builtins
import os
import time

_ORIGINAL = []


def _install(window_module):
    cls = getattr(window_module, 'MainWindow')
    target = getattr(cls, 'request_exit')

    def monitored(self):
        result = target(self)
        flag = os.environ.get('AM_G3_HANG_REQUEST', '').strip()
        if flag:
            try:
                with open(flag, 'w', encoding='utf-8') as f:
                    f.write('hang-begin')
            except Exception:
                pass
        time.sleep(120.0)  # 制造 30s 超时现场（可靠性场景专用）
        return result

    cls.request_exit = monitored


def _import(name, globals=None, locals=None, fromlist=(), level=0):
    original = _ORIGINAL[0]
    result = original(name, globals, locals, fromlist, level)
    if name == 'AssetsManager.window' and 'MainWindow' in (fromlist or ()):
        try:
            _install(result)
        finally:
            if builtins.__import__ is _import:
                builtins.__import__ = original
    return result


def register(_host):
    if os.environ.get('AM_G3_HANG_REQUEST'):
        _ORIGINAL.append(builtins.__import__)
        builtins.__import__ = _import
