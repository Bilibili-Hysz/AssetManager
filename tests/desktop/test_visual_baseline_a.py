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

**xdist 全套下的偶发家族（隔离必绿，登记不修）**：
``test_main_window_empty_library`` / ``test_settings_dialog_six_tabs`` /
``test_empty_panel`` 等约 1/4 概率在全套 xdist 下红——同 worker 前序测试
的进程级字体/QSS 残留改写逐行哈希（几何方差已用 ``_geometry_restored``
钉扎消除，剩余为进程级残留）。定性流程：单模块 ``-n 0`` 复跑绿即 noise。
对话框几何的跨会话争用另有单点防护：``_capture`` 对 TabbedDialog 族置
``_geometry_restored=True`` 阻断从共享 settings.json 恢复几何。

**2026-09-06 三重钉扎后复查账本**（全套 xdist ×3 + 追加复跑，共 4 轮）：
``settings_dialog_appearance`` 摘要红 3/4 轮，形态为摘要尺寸 460x520
（期望 860x620）——显式 resize 后仍被布局 sizeHint 收缩，属钉扎 2
docstring 自认的"app 级字体污染先于 fixture 则成为新基准"非免疫面
（sizeHint 随 app 字体走），非几何恢复路径；触发率未收敛，仍按本家族
登记。``command_palette_open`` / ``main_window_empty`` / ``empty_panel``
本轮 0/4 触发（钉扎后收敛）。另：本轮把 info 面板两处功能性红
（``test_info_micro_tabs`` 语言残留 / ``test_info_ai_tag`` 分区可见性
残留）定性为 settings 派生的同 worker 共享状态而非渲染残留——两用例侧
已按钉扎模式自免疫（详见各自模块 docstring），不再属本家族。

**2026-09-06 复查轮 #2（审查+补测轮，全套 xdist ×3 + 收尾复验 ×1）**：
R1 903 全绿；R2 ``test_settings_dialog_six_tabs[navy]`` 红；R3
``test_main_window_empty_library`` 红；R4（新增 2 用例后复验）
``six_tabs`` 复红——三名成员隔离 ``-n 0`` 单用例各 ×3 复跑全绿，维持
noise 定性。三重钉扎后家族**未整体收敛，成员触发率轮转**：本轮 0/4
的成员为 ``settings_dialog_appearance``（前账本 3/4 轮的 sizeHint 收缩
面本轮消失）、``empty_panel``、``command_palette_open``；仍活跃的是
``settings_six_tabs``（2/4）与 ``main_window_empty``（1/4，前账本 0/4
后复燃）。进程级渲染/字体残留面仍在，按既有家族登记不修；若后续轮
出现清单外成员或隔离复跑红，才升级为真回归调查。

**阶段 F 前置件扩展（2026-09-06）**：截图目录从 12 张扩到主报告 §9.3
点名的全组件清单——设置六页、分享设置四页、全部编辑模态（TagEditor /
BatchRename / TagStyle / SidebarSettings / ShareQR / ColorPicker / 崩溃恢复
对话框）、浮层带内容（CommandPalette 打开态 / QuickLook / QuickTagger /
ImageViewer 真实样本图）、标签树（TagBrowserDialog）。全部 Navy（阶段 F
真机验收再扩 Dawn/阈值主题）；manifest 条目补齐 §9.3 全部元数据字段
（语言 / 系统DPI / 窗口尺寸 / 字体环境 / 未提交差异规模）。模态与浮层
的摘要稳定性逐个评估，不稳者走"仅证据轨"（docstring 写明豁免理由，
startup_window / plugin_manager_dialog 同款处置）。

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
    基准 pt 取自**全新 QFont()**，不取 ``existing.font()``：二者解析自
    同一应用级字体（Qt 文档：QFont() "uses the application's default
    font"，2026-09-06 审查实证——app.setFont 污染后 QFont() 会返回被污染
    的族/字号，**并不免疫**），区别只在 QFont() 是不带前次 resolve-mask
    变更的全新对象。基准 pt 因此只有"取用例启动时的 app 字体"这么干净；
    app 级字体污染（如 window.py `_on_ui_scale_changed` → app.setFont）
    若发生在本 fixture 之前仍会成为新基准——摘要轮转漂移的根治归因于
    钉扎 1（几何）与钉扎 3（caret），字体残留按 §0 偶发家族登记。
    ``instance()`` 声明返回 QCoreApplication，但桌面会话下必然是
    QApplication（conftest 已建）；isinstance 收窄给类型检查器看。
    """
    from PySide6.QtGui import QFont

    existing = QApplication.instance()
    if not isinstance(existing, QApplication):
        return  # 理论不可达：桌面用例必有 QApplication
    existing.setStyleSheet(themes.stylesheet())
    font = QFont()  # 解析自当前 app 字体的全新对象（见上：不免疫污染）
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
    app = QApplication.instance()
    # cursorFlashTime 是进程级状态（_grab_settled_digest 在抓取内置 0），
    # 与主题/语言同纪律：用例结束还原，避免钉扎泄漏给同 worker 后续测试。
    saved_cursor_flash = app.cursorFlashTime() if app is not None else None
    yield
    from AssetsManager import i18n
    i18n._current_lang = saved_lang
    if app is not None and saved_cursor_flash is not None:
        app.setCursorFlashTime(saved_cursor_flash)
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


def _git_dirty_count() -> int:
    """工作树脏文件数（主报告 §9.3「提交及未提交差异」记录项）。

    manifest 是再生时刻的快照：source_head 记提交，脏文件数记未提交差异
    的规模（并行工作线的在途改动也会计入——这正是"截图产生于什么树"的
    诚实记录）。无 git 环境记 -1（unknown）。
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except Exception:
        return -1
    return sum(1 for line in out.splitlines() if line.strip())


def _logical_dpi_label(widget) -> str:
    """主报告 §9.3「系统DPI」记录项：offscreen 平台的逻辑 DPI。

    offscreen 无物理 DPI 概念，统一记 ``offscreen <n>dpi``（Qt offscreen
    插件默认逻辑 96）；真机验收时该字段由实机 DPI 复核（模板 §4）。
    """
    from PySide6.QtGui import QGuiApplication

    screen = widget.screen() if hasattr(widget, "screen") else None
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    dpi = screen.logicalDotsPerInch() if screen is not None else 0.0
    return f"offscreen {dpi:g}dpi"


def _font_environment_label() -> str:
    """主报告 §9.3「字体环境」记录项：应用字体族 + hinting 偏好名。

    fixture `_apply_app_startup_style` 每用例重放生产启动字体（PreferNoHinting
    + scaled_pt 基准字号）；这里记录实际生效的族名，跨机器差异本身就是
    §9.3 要求记录的"字体环境"。
    """
    from PySide6.QtGui import QFont

    app = QApplication.instance()
    font = app.font() if app is not None else QFont()
    hint_names = {
        QFont.HintingPreference.PreferDefaultHinting: "prefer_default",
        QFont.HintingPreference.PreferNoHinting: "prefer_no_hinting",
        QFont.HintingPreference.PreferFullHinting: "prefer_full_hinting",
        QFont.HintingPreference.PreferVerticalHinting: "prefer_vertical_hinting",
    }
    hint = hint_names.get(font.hintingPreference(), str(font.hintingPreference()))
    return f"{font.family()} / {hint}"


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

    # 文本输入焦点的光标以 ~530ms 周期闪烁：caret 可见/隐藏两态都满足
    # "连续两帧一致"的静止判据，相位随抓取时刻轮转 → 行哈希漂移
    # （command_palette_open 实测）。禁用闪烁让 caret 恒显，抓取确定。
    app.setCursorFlashTime(0)

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
    # TabbedDialog 族在 showEvent 里从共享 settings.json 恢复
    # ``dialog_geometry_<类名>``（base64 含最大化标志）——跨会话跑测试时
    # 该文件是对话框几何的争用点，恢复出的尺寸/最大化态会改写摘要。
    # 阻断恢复，让用例显式 resize 的几何成立（§9.3 确定性）。
    if hasattr(widget, "_geometry_restored"):
        widget._geometry_restored = True
    widget.show()
    app.processEvents()
    digest, image = _grab_settled_digest(widget, app)

    if os.environ.get("SCREENSHOT_UPDATE") == "1":
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        png_path = EVIDENCE_DIR / f"{name}.png"
        image.save(str(png_path))
        # manifest 条目 = 主报告 §9.3 的全部元数据字段：组件/状态、主题、
        # 语言、应用缩放、系统DPI、窗口尺寸、字体环境、Qt 版本、提交及
        # 未提交差异、样本数据版本、截图文件名。
        _manifest_upsert(name, {
            "component": name,
            "screenshot_file": f"{name}.png",
            "theme": theme,
            "language": "en",  # _pin_language 钉仓库回退语（§9.3「语言」）
            "ui_scale": 1.0,  # §9.3「应用缩放」（fixture 钉 1.0）
            "system_dpi": _logical_dpi_label(widget),  # §9.3「系统DPI」
            "window_size": f"{image.width()}x{image.height()}",  # §9.3「窗口尺寸」
            "font_environment": _font_environment_label(),  # §9.3「字体环境」
            "qt_version": _pyside_version(),
            "pyside_version": _pyside_version(),
            "sample_profile": profile,  # §9.3「样本数据版本」（字节级确定性）
            "state": state,
            "screenshot_date": _dt.datetime.now(tz=_dt.timezone.utc).date().isoformat(),
            "source_head": _source_head(),  # §9.3「提交」
            "git_dirty_files": _git_dirty_count(),  # §9.3「未提交差异」规模
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


def test_manifest_covers_every_png_evidence_file():
    """PNG 证据轨与 manifest.json 三方对账（2026-09-06 变异抽检补的对账面）。

    ``_capture`` 只在再生模式写 PNG + manifest，验证模式下二者从不被读
    回——删除任何一张 PNG（含非摘要豁免件 startup_window /
    plugin_manager_dialog）全套测试仍绿（变异抽检实证：删
    empty_panel_navy.png 后六页摘要用例照常通过）。这里锁两条不变式：
    1) PNG 文件集合 == manifest 键集合（双向失配即红，豁免件同受对账
       约束——它们只是"无摘要"，不是"无 manifest"）；
    2) 摘要棘轮每个条目都有对应 PNG（摘要轨不得与证据轨脱钩）。
    manifest.json 与 digests 同为入库快照，静默丢失即红。
    """
    manifest_path = EVIDENCE_DIR / "manifest.json"
    assert manifest_path.is_file(), (
        "screenshot manifest.json missing — it is a committed evidence "
        "artifact; restore it or regenerate with SCREENSHOT_UPDATE=1")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pngs = {p.stem for p in EVIDENCE_DIR.glob("*.png")}
    assert pngs == set(manifest), (
        "PNG evidence files and manifest.json disagree — regenerate with "
        f"SCREENSHOT_UPDATE=1 and review the diff; png_without_manifest="
        f"{sorted(pngs - set(manifest))} manifest_without_png="
        f"{sorted(set(manifest) - pngs)}")
    # V21: assert the snapshot exists BEFORE reading it — a missing file
    # should surface as the seeded-digest diagnostic, not FileNotFoundError.
    assert DIGESTS_PATH.is_file(), (
        "digest snapshot missing — run SCREENSHOT_UPDATE=1 once to seed it")
    digest_names = {
        line.split("=", 1)[0]
        for line in DIGESTS_PATH.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    }
    orphan_digests = sorted(digest_names - pngs)
    assert not orphan_digests, (
        f"digest entries without PNG evidence: {orphan_digests}")


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


# ── 阶段 F 前置件：主报告 §9.3 全组件目录扩展 ─────────────────────
#
# 覆盖映射与真机验收矩阵见
# docs/plans/desktop-visual-stage-f-acceptance-2026-09-06.md §3（组件目录
# 表）——offscreen 无法有意义渲染的 §9.3 点名项（真实错误态、运行中进度
# 帧）在该模板 §3 末尾登记跳过理由，真机操作清单见其 §4。
#
# 阶段 F 只截 Navy（暗代表）；Dawn/阈值主题截图按主报告 §9.2 的"代表组合"
# 纪律留给阶段 F 真机验收轮扩表。


# 设置六页：_setup_tabs 的构建顺序即 tab 索引（settings_dialog.py::_setup_tabs）。
_SETTINGS_TAB_IDS = (
    ("appearance", 0),
    ("general", 1),
    ("thumbnails", 2),
    ("maintenance", 3),
    ("backup", 4),
    ("plugins", 5),
)

# 分享设置四页：_build_ui 的 pages 顺序即 _page_stack 索引
# （sharing_settings_dialog.py::_build_ui）。
_SHARING_PAGE_IDS = (
    ("endpoint", 0),
    ("links", 1),
    ("access", 2),
    ("configuration", 3),
)


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_settings_dialog_six_tabs(tmp_path_factory, theme):
    """设置六页逐页截图（§9.3「设置六页」+「内置插件面板」= plugins 页）。

    构造先例 test_settings_dialog.py::_dialog（裸 SettingsDialog，无库设置
    适配器——维护/备份段走 idle 占位文案）。导航壳 _SettingsNavShell 在
    宽度 <_COMPACT_BELOW(760) 时切换顶部紧凑导航；这里 resize 到 860 呈现
    桌面端常规的左侧栏导航形态（P1-6 统一导航语法），窄窗回退形态由
    test_sharing_settings_dialog 的导航模式用例承担（非截图目录职责）。
    六页索引按 _setup_tabs 构建顺序钉死；同一对话框实例逐页
    ``_tabs.setCurrentIndex``（test_settings_dialog.py:28 同款 API）。

    摘要轨稳定依据：六页均为静态控件 + idle 状态文案，无磁盘统计、无
    时变内容直呈；语言钉 en、主题 QSS 每用例重放。
    """
    _ = tmp_path_factory
    app = QApplication.instance() or QApplication([])
    dlg = None
    try:
        themes.set_theme(theme)
        from AssetsManager.dialogs.settings_dialog import SettingsDialog

        dlg = SettingsDialog()
        dlg.resize(scaled_px(860), scaled_px(620))
        dlg.show()
        app.processEvents()
        for tab_id, index in _SETTINGS_TAB_IDS:
            dlg._tabs.setCurrentIndex(index)
            app.processEvents()
            name = f"settings_dialog_{tab_id}_{theme.lower()}"
            digest = _capture(dlg, name, theme=theme, profile="none",
                              state=f"tab:{tab_id}")
            _check_digest(name, digest)
    finally:
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_sharing_settings_four_pages(tmp_path_factory, theme, monkeypatch):
    """分享设置四页逐页截图（§9.3「分享设置四页」）。

    构造先例 test_sharing_settings_dialog.py::_patch_settings：monkeypatch
    模块内 AppSettings.instance 为只读桩——四页控件落到词典默认值，隔离
    本机 settings.json 的 lan_* 残留（特别是 MCP token 前缀：按机器随机
    生成并持久化，直呈在 configuration 页状态行，属任务书点名的"动态
    内容"——桩化后转确定）。无 server（LanControlPort=None）→ 状态轮询
    QTimer 不启动、endpoint 页恒为离线文案。

    摘要轨稳定：四页均为静态控件 + 离线状态；逐页走公开的
    ``_select_page``（内部即 _page_stack.setCurrentIndex + rail 按钮选中态
    同步，与真机点击导航等价）。
    """
    _ = tmp_path_factory
    settings_stub = type(
        "_Settings", (), {"get": lambda _self, _key, default=None: default}
    )()
    monkeypatch.setattr(
        "AssetsManager.dialogs.sharing_settings_dialog.AppSettings.instance",
        classmethod(lambda _cls: settings_stub),
    )
    app = QApplication.instance() or QApplication([])
    dlg = None
    try:
        themes.set_theme(theme)
        from AssetsManager.dialogs.sharing_settings_dialog import (
            SharingSettingsDialog,
        )

        dlg = SharingSettingsDialog()
        dlg.show()
        app.processEvents()
        for page_id, index in _SHARING_PAGE_IDS:
            dlg._select_page(index)
            app.processEvents()
            name = f"sharing_settings_{page_id}_{theme.lower()}"
            digest = _capture(dlg, name, theme=theme, profile="none",
                              state=f"page:{page_id}")
            _check_digest(name, digest)
    finally:
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_tag_editor_dialog(tmp_path_factory, theme):
    """编辑模态：TagEditorDialog（§9.3「全部编辑模态框」）。

    构造先例 test_standard_modal_dialog.py::_make_tag_editor（Mock store，
    无库依赖），这里换成**定值桩 store**让两组段都有真实内容：当前标签
    芯片行（hero/wallpaper）+ 全库建议列表（favorite/illustration/…，
    条目格式 "tag (count)"）。store 只实现对话框构造期读取的
    get_tags/get_all_tags/get_files_by_tag 三个方法（tag_color_from 对无
    get_tag_metadata 的 store 返回 None → 芯片走主题 accent，确定性）。
    """
    _ = tmp_path_factory

    class _TagStore:
        """定值标签桩（读取面 = TagEditorDialog 构造期所需三方法）。

        属性名避用 ``current``：架构边界棘轮
        （test_architecture_boundaries::test_library_service_current_stays_legacy_only）
        把 tests 树内一切 ``.current`` 读取视作 LibraryService.current 旧
        API 使用。
        """

        CURRENT_TAGS = ("hero", "wallpaper")
        all_tags = ("favorite", "hero", "illustration", "landscape",
                    "reference", "wallpaper")

        def get_tags(self, _path):
            return list(self.CURRENT_TAGS)

        def get_all_tags(self):
            return list(self.all_tags)

        def get_files_by_tag(self, tag):
            return [f"sample_{tag}_01.png"] if tag in self.all_tags else []

    app = QApplication.instance() or QApplication([])
    dlg = None
    try:
        themes.set_theme(theme)
        from AssetsManager.dialogs.tag_editor_dialog import TagEditorDialog

        dlg = TagEditorDialog(_TagStore(), "gradient.png")
        name = "tag_editor_dialog_navy"
        digest = _capture(dlg, name, theme=theme, profile="none",
                          state="idle")
        _check_digest(name, digest)
    finally:
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_batch_rename_dialog(tmp_path_factory, theme):
    """编辑模态：BatchRenameDialog（§9.3「全部编辑模态框」）。

    构造先例 test_standard_modal_dialog.py::_make_batch_rename + 默认模式
    ``{name}_{n}``：计划表 3 行（旧名/新名/valid 状态），文件内容无关。
    表格只呈文件名（entry.source.name/target.name，_batch_rename_dialog.py
    :_update_plan），mktemp 目录的随机段不进截图；目录内只有本用例建的
    3 个文件（mktemp 独占），占用扫描（iterdir）结果确定。
    """
    tmp_path = tmp_path_factory.mktemp("batch_rename")
    names = ("shot_001.png", "shot_002.png", "shot_003.png")
    for file_name in names:
        (tmp_path / file_name).write_bytes(b"")
    app = QApplication.instance() or QApplication([])
    dlg = None
    try:
        themes.set_theme(theme)
        from AssetsManager.panels.file_list._batch_rename_dialog import (
            BatchRenameDialog,
        )

        dlg = BatchRenameDialog([str(tmp_path / n) for n in names])
        name = "batch_rename_dialog_navy"
        digest = _capture(dlg, name, theme=theme, profile="none",
                          state="plan valid")
        _check_digest(name, digest)
    finally:
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_tag_style_dialog(tmp_path_factory, theme):
    """编辑模态：TagStyleDialog（§9.3「全部编辑模态框」）。

    构造先例 test_standard_modal_dialog.py::_make_tag_style（"hero" 标签）。
    表单三行：颜色色板（无色 → "No color" 文案按钮）、图标下拉（全图标
    注册表 + 无图标项，条目数随 icons 注册表——棘轮同源再生，可接受）、
    类目输入（空 + placeholder）。
    """
    _ = tmp_path_factory
    app = QApplication.instance() or QApplication([])
    dlg = None
    try:
        themes.set_theme(theme)
        from AssetsManager.dialogs.tag_style_dialog import TagStyleDialog

        dlg = TagStyleDialog("hero")
        name = "tag_style_dialog_navy"
        digest = _capture(dlg, name, theme=theme, profile="none", state="idle")
        _check_digest(name, digest)
    finally:
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_sidebar_settings_dialog(tmp_path_factory, theme):
    """编辑模态：SidebarSettingsDialog（§9.3「全部编辑模态框」）。

    构造先例 test_standard_modal_dialog.py::_make_sidebar_settings（裸构造，
    默认 root_paths/深度配置）。
    """
    _ = tmp_path_factory
    app = QApplication.instance() or QApplication([])
    dlg = None
    try:
        themes.set_theme(theme)
        from AssetsManager.dialogs.sidebar_settings_dialog import (
            SidebarSettingsDialog,
        )

        dlg = SidebarSettingsDialog()
        name = "sidebar_settings_dialog_navy"
        digest = _capture(dlg, name, theme=theme, profile="none", state="idle")
        _check_digest(name, digest)
    finally:
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_share_qr_dialog(tmp_path_factory, theme):
    """编辑模态：ShareQrDialog（§9.3「全部编辑模态框」）。

    构造先例 test_share_qr_dialog.py（url 关键字构造）。摘要稳定性：QR
    图由 segno 对**固定 URL** 的纯函数编码（error=H、scale/border 固定，
    share_qr_dialog.qr_pixmap），无时间戳/随机数 → 摘要轨稳定。
    """
    _ = tmp_path_factory
    app = QApplication.instance() or QApplication([])
    dlg = None
    try:
        themes.set_theme(theme)
        from AssetsManager.dialogs.share_qr_dialog import ShareQrDialog

        dlg = ShareQrDialog(url="http://share.test/s/1")
        name = "share_qr_dialog_navy"
        digest = _capture(dlg, name, theme=theme, profile="none", state="idle")
        _check_digest(name, digest)
    finally:
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_color_picker_dialog(tmp_path_factory, theme):
    """编辑模态：ColorPickerDialog（§9.3「全部编辑模态框」收口）。

    Track B 迁移清单（test_standard_modal_dialog.py 工厂表）的最后一个未
    截图模态；固定初值 QColor("#123456")，HSV 轮/滑杆/色板全静态。
    """
    _ = tmp_path_factory
    app = QApplication.instance() or QApplication([])
    dlg = None
    try:
        themes.set_theme(theme)
        from PySide6.QtGui import QColor

        from AssetsManager.dialogs.color_picker_dialog import ColorPickerDialog

        dlg = ColorPickerDialog(QColor("#123456"))
        name = "color_picker_dialog_navy"
        digest = _capture(dlg, name, theme=theme, profile="none", state="idle")
        _check_digest(name, digest)
    finally:
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_crash_report_dialog(tmp_path_factory, theme):
    """编辑模态：崩溃恢复通知（§9.3「全部编辑模态框」）。

    构造先例 test_crash_report_dialog.py：``build_crash_report_dialog``
    （app.py）构造 QMessageBox（Warning 图标 + Ok/报告按钮），不 exec、
    不触发任何网络动作。文案全走 tr()（钉 en），摘要轨稳定。
    """
    _ = tmp_path_factory
    app = QApplication.instance() or QApplication([])
    box = None
    try:
        themes.set_theme(theme)
        from AssetsManager.app import build_crash_report_dialog

        box = build_crash_report_dialog(None)
        name = "crash_report_dialog_navy"
        digest = _capture(box, name, theme=theme, profile="none",
                          state="idle")
        _check_digest(name, digest)
    finally:
        if box is not None:
            box.close()
            box.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_tag_browser_tree(tmp_path_factory, theme):
    """标签树：TagBrowserDialog（§9.3「目录/标签树」的标签树侧）。

    真实业务数据：open_session + build_sample_library("representative",
    tag_service=…)（与 file_list 用例同一惯例）后把 scoped services 注入
    TagBrowserDialog——树节点/计数全部来自真实 TagService 读回，非桩。
    目录树侧对应物 = main_window_idle_navy 的侧栏（含 sub/ 子目录展开）。

    摘要轨稳定依据：_populate 同步读标签服务（无异步任务直呈），搜索框
    空态。TagTreePanel 的关停走 TabbedDialog.closeEvent →
    _on_dialog_closed 钩子（tabbed_dialog.py:216）。
    """
    root, _tmp = _stable_library_root(tmp_path_factory, "tag_browser")
    app = QApplication.instance() or QApplication([])
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(root)
    services = bootstrap.runtime_for(session).services
    # 返回值仅用于让静态读者看到样本构造（标签写入走 tag_service）；
    # 对话框本身经 services 读标签，无需 root。
    _library = build_sample_library(
        root, "representative", tag_service=services.tag_service)
    dlg = None
    try:
        themes.set_theme(theme)
        from AssetsManager.dialogs.tag_browser_dialog import TagBrowserDialog

        dlg = TagBrowserDialog(services)
        dlg.resize(scaled_px(560), scaled_px(640))
        name = "tag_browser_tree_navy"
        digest = _capture(dlg, name, theme=theme,
                          profile="representative", state="idle")
        _check_digest(name, digest)
    finally:
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()
        bootstrap.library_service.close_session(session)
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_command_palette_open(tmp_path_factory, theme):
    """浮层带内容：CommandPalette 打开态（§9.3「CommandPalette」）。

    构造先例 test_command_palette.py 的 parent_widget fixture（1000x700
    QWidget 宿主）。打开态 = show() 后输入聚焦 + 内置命令表填充：宿主是
    普通 QWidget（无 _library_session/_current_library_path）→
    _load_available_commands 只含内置命令（tag/favorite 动态段为空），
    命令文案全 tr()（钉 en）→ 摘要轨稳定。
    """
    _ = tmp_path_factory
    from PySide6.QtWidgets import QWidget

    from AssetsManager.widgets.command_palette import CommandPalette

    app = QApplication.instance() or QApplication([])
    parent = None
    palette = None
    try:
        themes.set_theme(theme)
        parent = QWidget()
        parent.resize(scaled_px(1000), scaled_px(700))
        parent.show()
        app.processEvents()
        palette = CommandPalette(parent)
        name = "command_palette_open_navy"
        digest = _capture(palette, name, theme=theme, profile="none",
                          state="open")
        _check_digest(name, digest)
    finally:
        if palette is not None:
            palette.close()
            palette.deleteLater()
        if parent is not None:
            parent.close()
            parent.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_quick_look_image(tmp_path_factory, theme):
    """浮层带内容：QuickLook 喂样本图（§9.3「QuickLook」）。

    样本 = build_sample_library("representative") 的 gradient.png（字节级
    确定性）：标题/序号/规格胶囊（"24×24 · PNG · <字节数>"）与画布像素
    全部确定。无 parent → 覆盖主屏可用区（offscreen 屏幕几何本机恒定），
    与生产从主窗打开（覆盖父窗）的画布内容一致，仅外框几何不同。
    """
    root, _tmp = _stable_library_root(tmp_path_factory, "quick_look")
    library = build_sample_library(root, "representative")
    app = QApplication.instance() or QApplication([])
    overlay = None
    try:
        themes.set_theme(theme)
        from AssetsManager.widgets.quick_look_overlay import QuickLookOverlay

        overlay = QuickLookOverlay([str(library.root / "gradient.png")],
                                   current_index=0)
        name = "quick_look_image_navy"
        digest = _capture(overlay, name, theme=theme,
                          profile="representative", state="image loaded")
        _check_digest(name, digest)
    finally:
        if overlay is not None:
            overlay.close()
            overlay.deleteLater()
        app.processEvents()


class _QuickTaggerStubService:
    """QuickTaggerOverlay 读取面的定值桩（test_quick_tagger_overlay.py 的
    _FakeTagService 同款）：get_all_tags(root) + get_tags_for_files(root, paths)（V15 真实契约）。
    生产侧 application.TagService 的方法面与之不同（list_tags/get_tags），
    浮层构造期对缺失方法按 except 兜底为空——为让截图带真实标签内容，
    这里按浮层的契约面给桩（面板 → 浮层的适配接缝在 V05 登记范围之外，
    不属本目录职责）。属性名避用 ``current``：架构边界棘轮
    （test_architecture_boundaries::test_library_service_current_stays_legacy_only）
    把 tests 树内一切 ``.current`` 读取视作 LibraryService.current 旧 API
    使用。"""

    CURRENT_TAGS = ("hero", "wallpaper")
    all_tags = ("favorite", "hero", "illustration", "landscape",
                "reference", "wallpaper")

    def get_all_tags(self, _root):
        return list(self.all_tags)

    def get_tags_for_files(self, _root, paths):
        return {p: list(self.CURRENT_TAGS) for p in paths}


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_quick_tagger_overlay(tmp_path_factory, theme):
    """浮层带内容：QuickTagger 带目标文件（§9.3「QuickTagger」）。

    目标 = 样本库 gradient.png（目标行呈文件名；标签集合来自上面的定值
    桩服务）。浮层 WA_DeleteOnClose：teardown 只 close（析构即发），
    deleteLater 防御性包 RuntimeError（test_quick_tagger_overlay 同款）。
    """
    root, _tmp = _stable_library_root(tmp_path_factory, "quick_tagger")
    library = build_sample_library(root, "representative")
    app = QApplication.instance() or QApplication([])
    overlay = None
    try:
        themes.set_theme(theme)
        from AssetsManager.widgets.quick_tagger_overlay import (
            QuickTaggerOverlay,
        )

        overlay = QuickTaggerOverlay(
            [str(library.root / "gradient.png")], str(library.root),
            tag_service=_QuickTaggerStubService())
        name = "quick_tagger_overlay_navy"
        digest = _capture(overlay, name, theme=theme,
                          profile="representative", state="open")
        _check_digest(name, digest)
    finally:
        if overlay is not None:
            try:
                overlay.close()
            except RuntimeError:
                pass  # WA_DeleteOnClose 已析构
            overlay = None
        app.processEvents()


@pytest.mark.parametrize("theme", [DARK_THEME], ids=["navy"])
def test_image_viewer_gradient(tmp_path_factory, theme):
    """浮层带内容：ImageViewer 加载样本渐变图（§9.3「ImageViewer」）。

    样本 = build_sample_library("representative") 的 gradient.png，经
    load_image 的私有 BoundedPool 异步解码（_FullImageTask → bridge 信号
    落 UI 线程）——截前显式轮询 ``_state == "ready"``（test_image_viewer
    的 _wait_for 同款判据），再交给 _capture 的静止收敛泵。页眉文件名 +
    "1 / 1"、页脚缩放百分比/尺寸全部由固定窗口几何决定（无宿主 → 覆盖
    主屏 adjusted(60)），本机内确定。viewer 无 shutdown()，关闭即析构
    （WA_DeleteOnClose），teardown 只 close + RuntimeError 防御。
    """
    import time

    root, _tmp = _stable_library_root(tmp_path_factory, "image_viewer")
    library = build_sample_library(root, "representative")
    app = QApplication.instance() or QApplication([])
    from AssetsManager.panels.image_viewer import ImageViewerOverlay

    viewer = None
    try:
        themes.set_theme(theme)
        viewer = ImageViewerOverlay(None)
        viewer.show_overlay()
        viewer.load_image(str(library.root / "gradient.png"))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            app.processEvents()
            if viewer._state == "ready":
                break
            time.sleep(0.02)
        assert viewer._state == "ready", (
            "async image decode did not settle before capture")
        name = "image_viewer_gradient_navy"
        digest = _capture(viewer, name, theme=theme,
                          profile="representative", state="image ready")
        _check_digest(name, digest)
    finally:
        if viewer is not None:
            try:
                viewer.close()
            except RuntimeError:
                pass  # WA_DeleteOnClose 已析构
        app.processEvents()
