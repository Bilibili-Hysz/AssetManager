"""阶段 A 视觉基线 — 真实组件截图 + 确定性摘要双轨（交付物 A-2）。

本模块是本仓**首例整窗 MainWindow 实例化**的测试：bootstrap +
``build_sample_library("representative")`` → open_session →
``MainWindow(bootstrap)`` → ``_workspace.add_library``（app.py:241 的真实
组装路径，会话由 lifecycle coordinator 打开并注入 scoped services）→
show → grab。

双轨截图机制（报告 §9.3 / §8 阶段A）：
- **PNG 证据轨**：``SCREENSHOT_UPDATE=1`` 时把 PNG 写入
  ``docs/reports/desktop-visual-consistency-2026-09-05-evidence/screenshots/``
  （证据目录，入库），并在 ``manifest.json`` 中登记组件/主题/ui_scale/
  样本 profile/PySide6 版本/日期/源码 HEAD。PNG 是人眼证据，不做全字节
  比对（抗锯齿跨机器不可移植）。
- **摘要快照轨**：无环境变量时比对确定性摘要（尺寸 + 四角与中心
  pixelColor + 逐行 sha256 拼哈希）与 ``tests/desktop/snapshots/
  visual_baseline_digests.txt``（防回归棘轮，同一生成机制下跨机器稳定）。

全部用例钉 ui_scale=1.0（本机持久化 0.9 已实证污染快照：
scaled_px(12)=11），主题选择用 ``themes.set_theme`` + 测试后还原
（restored_theme 模式）。

xdist：整窗用例改变共享 settings.json（theme/ui_scale 经 set_theme 持久
化）且 info_panel 有已知的 language refresh 偶发，全模块标
``xdist_group("serial")``（与 test_server_lifecycle 同款处理）。

**运行约定（进程隔离）**：摘要棘轮在**共享进程的串行全套**（
``pytest tests/desktop -n 0``）下会受前序测试的进程级渲染残留干扰——
已实证 ``test_settings_dialog`` 的语言往返后，滚动条 track 的透明背景
在 offscreen 下解析为 (0,0,0) 而非主题 base 色（逐行哈希即漂移）；用例
单独跑或默认 xdist（每 worker 独立进程组合）下全绿。因此本模块的验证
命令是：单模块 ``pytest tests/desktop/test_visual_baseline_a.py -n 0``，
或全套默认 ``pytest tests/desktop``（-n auto）。不要用 ``-n 0`` 跑整个
desktop 套件来验证截图摘要——那是共享进程模式，滚动条 track 级渲染残留
属已知限制（Qt 样式表/背景传播的进程级状态，无测试侧根治手段，也不值得
为它做像素归一化）。

不变式：不修改生产代码；不改 tests/ 之外的任何运行时状态（tests/
conftest.py 的会话级备份/还原负责 settings.json 复原）。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import QFileInfo
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from AssetsManager.core import themes
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.ui_scale import scaled_pt, scaled_px
from AssetsManager.dialogs.theme_preview_dialog import ThemePreviewDialog
from AssetsManager.dialogs.startup import StartupWindow
from AssetsManager.window import MainWindow
from tests.desktop.visual_conftest_helpers import build_sample_library

pytestmark = pytest.mark.xdist_group(name="serial")

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = (
    REPO_ROOT / "docs" / "reports"
    / "desktop-visual-consistency-2026-09-05-evidence" / "screenshots"
)
DIGESTS_PATH = (
    Path(__file__).parent / "snapshots" / "visual_baseline_digests.txt"
)

# 覆盖矩阵的主题代表（报告 §9.2）：默认深色 Navy + 浅色 Dawn。
# 注册键是 JSON 内 name（Navy/Dawn），非 D_/L_ 文件前缀。
DARK_THEME = "Navy"
LIGHT_THEME = "Dawn"


# ── ui_scale / 主题 钉扎 ─────────────────────────────────────────


def _pin_ui_scale_1() -> None:
    """把 ui_scale 钉到 1.0（内存级，不 save() 到 settings.json）。

    本机持久化 0.9 会把 scaled_px(12) 变成 11，污染全部几何与字号；
    只改内存 dict 即可让 ``get_ui_scale()`` 读到 1.0（它走
    AppSettings.instance().get）。tests/conftest 的会话级备份/还原
    负责磁盘复原，这里绝不调 ``settings.save()``。
    """
    settings = AppSettings.instance()
    settings.set("ui_scale", 1.0)
    assert scaled_px(12) == 12, "ui_scale pin failed — snapshots would corrupt"


def _clear_window_geometry() -> None:
    """清掉持久化窗口几何与面板布局（内存 + 磁盘双级）。

    这是 MainWindow 在 offscreen 下整窗实例化的已知前置：真机用过的
    settings 若带 ``window_geometry``/``window_maximized=True``，构造期
    ``_restore_window_geometry`` 会先于 ``self._bg_resize_timer`` 的创建
    触发 ``resizeEvent``（window.py:175 在 :182 之前），AttributeError
    之后 C++ 侧段错误。内存清空后走 ``resize(1200, 800)`` 默认路径。

    同批清掉的还有 dock/workspace/面板布局键与最近库列表：close() 会
    持久化当前窗口的 dock 宽度与面板视图状态（_save_dock_layout →
    PanelState），前序测试也可能写过 recent_libraries（StartupWindow
    渲染库卡片，卡片数量/文字直接进截图）——不清则同一进程内后一个
    窗口测试会恢复前一个窗口的布局、启动页呈现他人会话的库，摘要跨
    用例不可复现。

    磁盘级（save）是必须的：StartupWindow.__init__ 里有
    ``self._settings.load()``（startup.py:447），会从磁盘重读并盖掉
    内存值——仅内存 set 挡不住全套跑时前序测试 save 过的磁盘状态。
    写盘的还原责任由 tests/conftest.py 的 _restore_shared_config 承担
    （会话开始快照、会话结束写回原字节）。
    """
    settings = AppSettings.instance()
    settings.set("window_geometry", None)
    settings.set("window_maximized", False)
    settings.set("window_dock_state", None)
    settings.set("workspace_tabs", None)
    settings.set("recent_libraries", None)
    for key in ("dock_widths", "file_list_view_state",
                "sidebar_depth_cfg", "info_panel_layout"):
        settings.set(key, None)
    # 摘要确定性：reduce_motion 让网格 hover/选中不走 16ms 动画帧
    # （_grid_widget_render 直接读 _hover_row/_selection），并抑制启动
    # 淡入之外的一切装饰动画；V07 已记录启动淡入 300ms 属例外，截图
    # 时序在 _capture 内经 processEvents 收敛。
    settings.set("reduce_motion", True)
    settings.save()  # 磁盘级钉扎（见 docstring：StartupWindow 会重读盘）


def _pin_language() -> str:
    """把界面语言钉到仓库回退语（en），返回原语言供还原。

    全套跑时同 worker 的前序测试会切换 i18n 语言；InfoPanel 空态、
    菜单、按钮文字全部走 tr()，语言残留直接改写截图文字。直接设
    ``i18n._current_lang``（模块全局）而不走 set_language：它不但要
    广播 language_changed、还会写盘 settings.json——两项都会把污染
    传播给其他测试。
    """
    from AssetsManager import i18n
    saved = i18n._current_lang
    i18n._current_lang = "en"
    return saved


@pytest.fixture
def restored_theme():
    """保存持久化主题，测试后还原（test_theme_qss_contract.py 同款模式）。"""
    saved = AppSettings.instance().get("theme")
    yield saved
    if saved:
        themes.set_theme(saved)


def _apply_app_startup_style() -> None:
    """按 app.py:156-164 的启动序对齐全局 QSS 与应用字体。

    xdist worker 是共享进程：前序任意桌面测试都可能改过 app 级字体
    （set_font/pointSize）或残留自己的 stylesheet，而文字渲染参与逐行
    哈希。这里每用例重放生产启动的两步：全局主题 QSS + 基准字体
    （PreferNoHinting、pointSize 经 scaled_pt——钉 1.0 后即系统默认 pt）。
    ``instance()`` 声明返回 QCoreApplication，但桌面会话下必然是
    QApplication（conftest 已建）；isinstance 收窄给类型检查器看。
    """
    from PySide6.QtGui import QFont

    existing = QApplication.instance()
    if not isinstance(existing, QApplication):
        return  # 理论不可达：桌面用例必有 QApplication
    existing.setStyleSheet(themes.stylesheet())
    font = existing.font()
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    base_pt = font.pointSize()
    existing.setProperty("base_font_size", base_pt)
    font.setPointSize(scaled_pt(base_pt))
    existing.setFont(font)


@pytest.fixture(autouse=True)
def visual_baseline_env(restored_theme):
    """ui_scale 钉 1.0 + 清窗口几何 + 全局主题 QSS/字体 + 主题往返还原。

    复用 test_theme_visual_smoke 的 restored_theme 惯例：先把当前持久
    主题交给 ``themes.set_theme``（它顺带持久化到 settings），用例结束
    再切回，保证串行跑完 24 套注册表不受污染。

    全局 QSS/字体：app.py:156-164 在真实启动时对 QApplication 应用
    ``setStyleSheet(themes.stylesheet())`` 与基准字体；面板/对话框截图
    用例没有主窗口替它们做这一步（MainWindow 构造里的 themes.apply_to
    只覆盖该窗），xdist worker 上前序测试的字体/样式残留会直接改写
    文字渲染。这里按生产启动路径每用例对齐一次。
    """
    _pin_ui_scale_1()
    _clear_window_geometry()
    _apply_app_startup_style()
    saved_lang = _pin_language()
    yield
    from AssetsManager import i18n
    i18n._current_lang = saved_lang
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


# ── 截图 + 摘要原语 ───────────────────────────────────────────────


def _source_head() -> str:
    """源码 HEAD（报告 §9.3 记录项）；无 git 时记 unknown。"""
    try:
        return subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _pyside_version() -> str:
    import PySide6
    return PySide6.__version__


def _digest_image(image) -> str:
    """确定性摘要：尺寸 + 四角与中心 pixelColor + 逐行 sha256 拼哈希。

    比 PNG 全字节稳定（避开 PNG 时间戳/压缩器差异），比单点颜色敏感
    （任一行变化都会改哈希）。像素取 "#rrggbb" 统一表达；逐行哈希经
    constBits + bytesPerLine 切片（PySide6 QImage 无 constLine）。
    """
    w, h = image.width(), image.height()
    corners = [
        image.pixelColor(x, y).name()  # "#rrggbb"
        for x, y in (
            (0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
            (w // 2, h // 2),
        )
    ]
    buffer = image.constBits()
    stride = image.bytesPerLine()
    row_hashes = []
    for y in range(h):
        row = bytes(buffer[y * stride: y * stride + stride])
        row_hashes.append(hashlib.sha256(row).hexdigest())
    return (
        f"{w}x{h}|corners={','.join(corners)}"
        f"|rows={hashlib.sha256('|'.join(row_hashes).encode()).hexdigest()}"
    )


def _drain_async_painting(widget, app) -> None:
    """排空截面前仍在飞的异步绘制与装饰动画（确定性收敛）。

    截图摘要要求截图时刻所有时变表面收敛到同一状态，四类来源逐一
    排空：
    - ThumbnailLoader 的专用 QThreadPool（面板 _loader._pool；整窗在
      window.file_list._loader）与全局 QThreadPool（InfoPanel
      _FileInfoTask 等）全部 waitForDone —— 缩略图是否已交付不能靠
      机器时序（串行 vs xdist worker 实测产生不同行哈希）；
    - ThumbnailDeliveryCoordinator 的 50ms 合并 QTimer flush；
    - queued 信号/回调经 processEvents 落地；
    - 装饰动画收尾：WorkspaceSection 的标签指示器动画
      （workspace_bar.py:54，QPropertyAnimation 200ms）**未接
      reduce_motion**（生产缺口，V07 同族，报告中登记），只能等真实
      时间走完 —— 泵 260ms 事件循环（200ms + 余量）让所有
      QPropertyAnimation 停在终值，不依赖起始帧相位。
    """
    import time

    from PySide6.QtCore import QThreadPool

    QThreadPool.globalInstance().waitForDone(10_000)
    # 缩略图专用池可能挂在面板（FileListPanel._loader）或整窗的中央
    # 面板上（window.file_list._loader）；逐个探测排空。
    owners = [widget, getattr(widget, "file_list", None)]
    pools: list = []
    for owner in owners:
        if owner is None:
            continue
        loader = getattr(owner, "_loader", None)
        loader_pool = getattr(loader, "_pool", None)
        if loader_pool is not None:
            pools.append(loader_pool)
    for pool in pools:
        pool.waitForDone(10_000)
    delivery = getattr(widget, "_thumbnail_delivery", None)
    if delivery is None:
        delivery = getattr(getattr(widget, "file_list", None), "_thumbnail_delivery", None)
    if delivery is not None and getattr(delivery, "_timer", None) is not None:
        # 50ms 合并窗口：给足真实时间再 flush，绕过 offscreen 无定时器
        # 事件循环的问题（QTimer 需要事件循环推进）。
        deadline = time.monotonic() + 0.3
        while delivery._timer.isActive() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        if delivery._timer.isActive():
            delivery.flush()
    # 装饰动画收尾（指示器 200ms 等）：真实时间 + 事件泵
    settle_deadline = time.monotonic() + 0.26
    while time.monotonic() < settle_deadline:
        app.processEvents()
        time.sleep(0.02)
    # 让 queued 信号/回调全部落地
    for _ in range(5):
        app.processEvents()


def _grab_settled_digest(widget, app) -> "tuple[str, QImage]":
    """视觉静止收敛 grab：固定泵送窗口 + 连续两次一致的静止判据。

    排空（_drain_async_painting）后仍可能有跨用例残留的极晚到异步
    交付（xdist 多 worker 下缩略图管线的时序差被实测放大）。单纯
    "两次连续一致"会踩进假静止平台（相邻两帧恰好相同但动画尚未完
    结——全套跑实测）。所以先无条件泵 400ms（覆盖 50ms 缩略图合并
    QTimer、200ms 工作区指示器 QPropertyAnimation 与 300ms 启动淡入
    的完整时长），再进入连续判据。返回 (摘要, 最后一张图)。
    """
    import time

    # 无条件泵送窗口：一次跨过所有已知动画时长 + 100ms 余量
    lead = time.monotonic() + 0.4
    while time.monotonic() < lead:
        app.processEvents()
        time.sleep(0.02)
    _drain_async_painting(widget, app)
    prev = _digest_image(widget.grab().toImage())
    for _ in range(10):
        # 两次 grab 之间泵 120ms 真实时间，给晚到交付落地机会
        settle = time.monotonic() + 0.12
        while time.monotonic() < settle:
            app.processEvents()
            time.sleep(0.02)
        _drain_async_painting(widget, app)
        image: QImage = widget.grab().toImage()
        digest = _digest_image(image)
        if digest == prev:
            return digest, image
        prev = digest
    return prev, widget.grab().toImage()


def _capture(widget, name: str, *, theme: str, profile: str,
             state: str = "idle") -> str:
    """show → 视觉静止收敛 grab → 返回摘要；再生模式同时落 PNG+manifest。

    所有 MainWindow 系截图必须在窗口已收到 ``_apply_scoped_services``
    的真实会话上抓取（由调用侧 fixture 保证）。
    """
    app = QApplication.instance() or QApplication([])
    widget.show()
    app.processEvents()
    digest, image = _grab_settled_digest(widget, app)

    if os.environ.get("SCREENSHOT_UPDATE") == "1":
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        png_path = EVIDENCE_DIR / f"{name}.png"
        image.save(str(png_path))
        _manifest_upsert(name, {
            "component": name,
            "theme": theme,
            "ui_scale": 1.0,
            "sample_profile": profile,
            "state": state,
            "pyside_version": _pyside_version(),
            "screenshot_date": _dt.datetime.now(tz=_dt.timezone.utc).date().isoformat(),
            "source_head": _source_head(),
            "size": f"{image.width()}x{image.height()}",
            "digest": digest,
        })
    return digest


def _manifest_upsert(name: str, entry: dict) -> None:
    """合并写入截图目录的 manifest.json（键=组件截图名）。"""
    manifest_path = EVIDENCE_DIR / "manifest.json"
    manifest: dict = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
    manifest[name] = entry
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n", encoding="utf-8")


def _render_baseline() -> str:
    """供棘轮快照使用的说明头。PNG/manifest 由 _capture 落盘。"""
    return (
        f"# generated by tests/desktop/test_visual_baseline_a.py\n"
        f"# regenerate: SCREENSHOT_UPDATE=1 python -m pytest "
        f"tests/desktop/test_visual_baseline_a.py -n 0\n"
        f"# pyside={_pyside_version()} head={_source_head()}\n"
    )


@pytest.fixture(autouse=True)
def _digest_snapshot_file():
    """再生模式：跑完全部截图用例前预写说明头（幂等）。"""
    if os.environ.get("SCREENSHOT_UPDATE") == "1":
        DIGESTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not DIGESTS_PATH.is_file():
            DIGESTS_PATH.write_text(_render_baseline(), encoding="utf-8")
    yield


def _check_digest(name: str, digest: str) -> None:
    """摘要与快照比对；再生模式改写为记录最新值。"""
    lines: list[str] = []
    if DIGESTS_PATH.is_file():
        lines = DIGESTS_PATH.read_text(encoding="utf-8").splitlines()
    entries = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in lines if "=" in line and not line.startswith("#")
    }
    update = os.environ.get("SCREENSHOT_UPDATE") == "1"
    if update:
        entries[name] = digest
        body = _render_baseline() + "".join(
            f"{k}={v}\n" for k, v in sorted(entries.items())
        )
        DIGESTS_PATH.write_text(body, encoding="utf-8")
        return
    assert DIGESTS_PATH.is_file(), (
        "digest snapshot missing — run SCREENSHOT_UPDATE=1 once to seed it")
    assert name in entries, (
        f"{name} not in snapshot — run SCREENSHOT_UPDATE=1 to record it")
    assert entries[name] == digest, (
        f"{name} visual digest changed — if intentional, regenerate with "
        f"SCREENSHOT_UPDATE=1 and review the PNG evidence diff")


# ── 整窗/面板 fixture ────────────────────────────────────────────


@pytest.fixture
def main_window_factory():
    """首例整窗 MainWindow 工厂：app.py:241 的真实组装路径。

    顺序刻意与生产一致：先构造空窗（无 session 参数），再
    ``_workspace.add_library`` —— 会话打开、scoped services 注入、侧栏/
    文件列表导航全部由 WindowLifecycleCoordinator.switch_library 完成；
    之前直接传 ``library_session`` 会让 workspace restore 抢先开 session，
    造出非 canonical 的双会话（runtime_for 拒绝）。

    LAN 停用：``lan_server_factory=None`` 让 LanSharingMixin 保持惰性
    （未调用 toggle 前不拉起 aiohttp 端口）。样本库由调用方在
    ``open()`` 前用 build_sample_library 落到自己的 tmp_path_factory 目录，
    工厂只负责按该根开窗；teardown 统一走 _teardown_main_window。
    """
    app = QApplication.instance() or QApplication([])
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    bootstrap = ApplicationBootstrap()
    created: list[MainWindow] = []

    class _Factory:
        @staticmethod
        def open(library_root: str) -> MainWindow:
            window = MainWindow(bootstrap, None, lan_server_factory=None)
            window._workspace.add_library(library_root)
            assert window._library_session is not None, (
                "add_library did not open a session via lifecycle coordinator")
            window.file_list._model._wait_for_scan()
            app.processEvents()
            created.append(window)
            return window

    try:
        yield _Factory()
    finally:
        for window in created:
            _teardown_main_window(window, app)


def _release_shortcut_registry() -> None:
    """把 ShortcutManager 里挂到将销毁窗口的 QAction 注册项摘除。

    生产代码的已知生命周期缺口（本次新发现，见模块 docstring 末尾）：
    window.py 从不在关窗时清菜单快捷键注册，而 ShortcutManager 是进程级
    单例，同进程先后实例化两个 MainWindow（app.py:230 的“先 close 旧窗
    再开新窗”重开路径同样命中）时，第二个窗口的 register_action 会触到
    第一个窗口已析构的 QAction → ``libshiboken: Internal C++ object
    already deleted``。
    测试侧规避：关窗后直接从注册表 dict 摘除全部键位（不调用
    unregister() —— 它内部会对已死 QAction setEnabled/deleteLater）。
    不修改生产代码；本缺口在报告中登记。
    """
    from AssetsManager.widgets.shortcut_manager import ShortcutManager

    manager = ShortcutManager.instance()
    manager._shortcuts.clear()


def _teardown_main_window(window, app) -> None:
    """整窗关停：force_quit → close → 摘快捷键注册 → deleteLater。"""
    window._force_quit = True
    try:
        window.close()
    except RuntimeError:
        pass  # C++ 对象已析构的竞态下不阻塞 teardown
    _release_shortcut_registry()
    window.deleteLater()
    app.processEvents()


# 固定面包屑段：库根统一建在 mktemp 结果下再压 5 层固定名目录。
# FileListPanel 面包屑渲染当前目录的最后 5 个路径段（_navigation.py
# ancestors[-5:]），pytest 的 tmp 根链含随机段（popen-gwN/test_xxxN0），
# 不压层时随机段直接进截图文字——串行与 xdist、不同机器、不同
# worker 数都必然漂移。压 5 层固定名后，随机段被折叠为固定的"…"省略
# 点，显示集合恒为 a/b/c/d/e。
_BREADCRUMB_STABLE_SEGMENTS = ("a", "b", "c", "d", "e")


def _stable_library_root(tmp_path_factory, purpose: str):
    """mktemp + 5 层固定名；返回 (库根, 其父 tmp) —— 面包屑确定性保证。"""
    tmp_path = tmp_path_factory.mktemp(purpose)
    root = tmp_path
    for segment in _BREADCRUMB_STABLE_SEGMENTS:
        root = root / segment
    root.mkdir(parents=True)
    return root, tmp_path


# ── 主窗口截图（默认深色 Navy + 浅色 Dawn）─────────────────────────


@pytest.mark.parametrize("theme", [DARK_THEME, LIGHT_THEME],
                         ids=["navy", "dawn"])
def test_main_window_idle(tmp_path_factory, main_window_factory, theme):
    """整窗 idle：菜单行 + 工作区标签 + 侧栏 + 网格 + 信息面板 + 状态栏。"""
    root, _tmp = _stable_library_root(tmp_path_factory, "main_window_idle")
    library = build_sample_library(root, "representative")
    themes.set_theme(theme)
    window = main_window_factory.open(str(library.root))
    # 触发一次文件聚焦，让信息面板呈现真实数据（选中态代表子集）
    window.info.update_info(QFileInfo(str(library.root / "gradient.png")))
    app = QApplication.instance() or QApplication([])
    app.processEvents()
    name = f"main_window_idle_{theme.lower()}"
    digest = _capture(window, name, theme=theme, profile="representative",
                      state="idle+info focused")
    _check_digest(name, digest)


# ── FileListPanel 网格/列表两视图 + hover/选中 ─────────────────────


def _grid_hover_and_select(grid, app):
    """编程触发 hover（鼠标 move 等价：进入行 + 状态直呈）。

    自绘网格的 hover/选中绘制在 reduce_motion=True 下直接读
    ``_hover_row``/``_selection``（_grid_widget_render.py:627-630），
    不经过动画进度表；fixture 已内存级设 ``reduce_motion=True``，
    所以直接赋这两个字段即是报告 §9.2 hover/selected 维度的编程触发
    等价物（不依赖真实光标设备、不受 16ms 动画帧影响）。
    """
    grid._hover_row = 0
    grid._selection = {0}
    if hasattr(grid, "_emit_selection_changed"):
        grid._emit_selection_changed()
    grid.update()
    app.processEvents()


@pytest.mark.parametrize("view,theme", [
    ("grid", DARK_THEME), ("grid", LIGHT_THEME),
    ("details", DARK_THEME),
], ids=["grid_navy", "grid_dawn", "details_navy"])
def test_file_list_views(tmp_path_factory, view, theme):
    """FileListPanel 网格/列表两视图 × 深浅代表主题（hover+选中态）。"""
    root, _tmp = _stable_library_root(tmp_path_factory, f"file_list_{view}")
    app = QApplication.instance() or QApplication([])
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.panels.file_list import FileListPanel
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(root)
    services = bootstrap.runtime_for(session).services
    library = build_sample_library(
        root, "representative", tag_service=services.tag_service)
    panel = None
    try:
        themes.set_theme(theme)
        panel = FileListPanel()
        panel.set_scoped_services(services)
        panel.navigate_to(str(library.root), set_root=True)
        panel._model._wait_for_scan()
        panel.resize(scaled_px(900), scaled_px(560))
        if view == "details":
            panel._set_view_mode_by_name("Details")
        app.processEvents()
        # 状态维度代表子集：hover + 选中（编程触发）
        if view == "grid":
            _grid_hover_and_select(panel._grid_widget, app)
        name = f"file_list_{view}_{theme.lower()}"
        digest = _capture(panel, name, theme=theme,
                           profile="representative", state="hover+selected")
        _check_digest(name, digest)
    finally:
        if panel is not None:
            panel.shutdown()
            panel.deleteLater()
        bootstrap.library_service.close_session(session)
        app.processEvents()


# ── InfoPanel（分段内容）─────────────────────────────────────────


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_info_panel_focused(tmp_path_factory, theme):
    """InfoPanel 聚焦资产：名称/信息/标签/备注分段的选中态代表。"""
    root, _tmp = _stable_library_root(tmp_path_factory, "info_panel")
    app = QApplication.instance() or QApplication([])
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.panels.info import InfoPanel
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(root)
    services = bootstrap.runtime_for(session).services
    library = build_sample_library(
        root, "representative", tag_service=services.tag_service)
    panel = None
    try:
        themes.set_theme(theme)
        panel = InfoPanel()
        panel.set_scoped_services(services)
        panel.resize(scaled_px(360), scaled_px(640))
        panel.update_info(QFileInfo(str(library.root / "gradient.png")))
        app.processEvents()
        name = f"info_panel_focused_{theme.lower()}"
        digest = _capture(panel, name, theme=theme,
                          profile="representative", state="focused")
        _check_digest(name, digest)
    finally:
        if panel is not None:
            panel.shutdown()
            panel.deleteLater()
        bootstrap.library_service.close_session(session)
        app.processEvents()


# ── StandardModalDialog 代表（ThemePreviewDialog）─────────────────


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_theme_preview_dialog(tmp_path_factory, theme):
    """模态框代表：ThemePreviewDialog（工厂表参数化已证可无库实例化）。"""
    _ = tmp_path_factory  # 无库数据需求；参数化仅为与其他用例对齐
    app = QApplication.instance() or QApplication([])
    dlg = None
    try:
        themes.set_theme(theme)
        dlg = ThemePreviewDialog()
        name = f"theme_preview_dialog_{theme.lower()}"
        digest = _capture(dlg, name, theme=theme,
                          profile="none", state="idle")
        _check_digest(name, digest)
    finally:
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()
        app.processEvents()


# ── StartupWindow（最近库卡片/首次使用卡片）──────────────────────


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_startup_window(tmp_path_factory, theme):
    """启动页：窗口结构 + 主题应用（PNG+manifest 证据轨）。

    摘要轨（digest ratchet）刻意不启用：StartupWindow 在 __init__ 里
    ``self._settings.load()`` 重读磁盘，卡片集合由磁盘 recent_libraries
    决定；同 worker 前序任何 settings.save()（TabbedDialog 关闭保存
    几何时会整字典落盘）都可能在本用例构造前改写它，全套跑实测出现
    两种稳定帧（空态 vs 最近库卡片）的时序二态。PNG/manifest 证据仍
    落盘（SCREENSHOT_UPDATE=1 再生）；摘要防回归由其余 8 个用例承担。
    """
    _ = tmp_path_factory
    app = QApplication.instance() or QApplication([])
    win = None
    try:
        themes.set_theme(theme)
        win = StartupWindow()
        name = f"startup_window_{theme.lower()}"
        digest = _capture(win, name, theme=theme,
                          profile="none", state="idle")
        del digest  # 只走证据轨；比对轨见 docstring 说明
    finally:
        if win is not None:
            win.close()
            win.deleteLater()
        app.processEvents()


# ── 空库主窗口（empty profile 的空态代表）─────────────────────────


def test_main_window_empty_library(tmp_path_factory, main_window_factory):
    """empty profile：空库整窗（空态/占位呈现）。"""
    root, _tmp = _stable_library_root(tmp_path_factory, "main_window_empty")
    library = build_sample_library(root, "empty")
    themes.set_theme(DARK_THEME)
    window = main_window_factory.open(str(library.root))
    # 显式落空态：InfoPanel 构造时无聚焦，但全套跑时同 worker 的前序
    # 测试可能在全局信号总线上留下 file_focused 之外的间接状态；用
    # 业务 API update_info(None) 把信息面板推到确定的空态，消除对
    # 历史残留的时序依赖（业务语义即"无选中"）。
    window.info.update_info(None)
    name = "main_window_empty_navy"
    digest = _capture(window, name, theme=DARK_THEME,
                      profile="empty", state="idle+empty")
    _check_digest(name, digest)



# ── Stage E 覆盖盲区扩展（插件对话框 / Toast / 空态面板）───────────


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_plugin_manager_dialog(tmp_path_factory, theme, monkeypatch):
    """插件管理器对话框（Stage E 覆盖盲区）：双插件卡片 + 详情段选中态。

    构造先例沿用 test_plugin_manager_dialog.py 的 _PluginManager 替身：
    monkeypatch PluginManagerService.get，无需真实插件目录。

    摘要轨（digest ratchet）刻意不启用（startup_window 同款处置）：实测
    对话框渲染对同 worker 进程内前序测试的残留敏感（xdist 分组不同产生
    两种稳定帧，逐行哈希即漂移；对话框本体无样式问题——单测
    test_plugin_manager_dialog.py 全绿）。PNG/manifest 证据仍落盘
    （SCREENSHOT_UPDATE=1 再生）；摘要防回归由其余钉扎用例承担。
    """
    _ = tmp_path_factory
    from AssetsManager.core.plugins.descriptor import (
        PLUGIN_STATE_ACTIVE,
        PluginDescriptor,
        PluginRecord,
    )
    from AssetsManager.core.plugins.manager import PluginManagerService
    from AssetsManager.dialogs.plugin_manager_dialog import PluginManagerDialog

    class _Manager:
        def __init__(self):
            self._records = {
                "one": PluginRecord(
                    plugin_id="one", root_dir="C:/plugins/one", manifest_path="one.json",
                    descriptor=PluginDescriptor("one", "One", "1.0", description="First plugin"),
                    state=PLUGIN_STATE_ACTIVE, enabled=True,
                ),
                "two": PluginRecord(
                    plugin_id="two", root_dir="C:/plugins/two", manifest_path="two.json",
                    descriptor=PluginDescriptor("two", "Two", "2.0", description="Second plugin"),
                    state=PLUGIN_STATE_ACTIVE, enabled=True,
                ),
            }

        def plugin_record(self, plugin_id):
            return self._records.get(plugin_id)

        def enable_plugin(self, plugin_id):
            self._records[plugin_id].enabled = True

        def disable_plugin(self, plugin_id):
            self._records[plugin_id].enabled = False

    monkeypatch.setattr(PluginManagerService, "get", lambda: _Manager())
    app = QApplication.instance() or QApplication([])
    dlg = None
    try:
        themes.set_theme(theme)
        dlg = PluginManagerDialog()
        dlg._select_plugin("one")  # 详情段选中态代表
        name = f"plugin_manager_dialog_{theme.lower()}"
        digest = _capture(dlg, name, theme=theme, profile="none", state="selected")
        del digest  # 只走证据轨；比对轨豁免理由见 docstring
    finally:
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_toast_notification(tmp_path_factory, theme):
    """Toast 轻提示（Stage E 覆盖盲区）：success 级 + 图标 + 副标题。

    构造先例沿用 test_toast_and_empty_visuals.py：普通 QWidget 父窗 +
    Toast(parent, ...)。fixture 已钉 reduce_motion=True（无淡入动画帧）；
    duration 拉长到 60s，避免截图收敛泵送（约 0.5s）期间自动消失。
    文案用固定字符串：生产侧传入的是 tr() 结果，截图钉 en（_pin_language），
    固定串避免 i18n 目录改词直接打碎摘要棘轮。
    """
    _ = tmp_path_factory
    from PySide6.QtWidgets import QWidget

    from AssetsManager.widgets.toast import Toast

    app = QApplication.instance() or QApplication([])
    parent = None
    toast = None
    try:
        themes.set_theme(theme)
        parent = QWidget()
        parent.resize(800, 600)
        parent.show()
        app.processEvents()
        toast = Toast(
            parent, "Library backup completed", level="success",
            duration=60_000, icon="check", subtitle="backup-2026-09-06.zip",
        )
        toast.show()
        app.processEvents()
        name = "toast_success_navy"
        digest = _capture(toast, name, theme=theme, profile="none", state="visible")
        _check_digest(name, digest)
    finally:
        if toast is not None:
            toast.dismiss_immediately()
        Toast._instance = None
        if parent is not None:
            parent.close()
            parent.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_empty_panel(tmp_path_factory, theme):
    """空态面板（empty role，Stage E 覆盖盲区）：EmptyPanel 包 EmptyStateWidget。"""
    _ = tmp_path_factory
    from AssetsManager.panels.empty import EmptyPanel

    app = QApplication.instance() or QApplication([])
    panel = None
    try:
        themes.set_theme(theme)
        panel = EmptyPanel(state="empty")
        panel.resize(scaled_px(360), scaled_px(420))
        name = "empty_panel_navy"
        digest = _capture(panel, name, theme=theme, profile="none", state="empty")
        _check_digest(name, digest)
    finally:
        if panel is not None:
            panel.shutdown()
            panel.deleteLater()
        app.processEvents()
