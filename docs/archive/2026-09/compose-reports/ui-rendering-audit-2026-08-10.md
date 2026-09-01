# 桌面端 UI 绘制/图标/SVG 审查记录 — 2026-08-10（第一次审查）

> **去重指针(2026-08-27)**:本文件与 [`docs/archive/2026-09/reports-superseded/ui-rendering-audit-2026-08-10.md`](../reports-superseded/ui-rendering-audit-2026-08-10.md) 为同一审查的复本;查阅以 `docs/reports/` 版为准,本复本仅保留证据。
> 状态：**待双代理独立审计**（audit-1 / audit-2 输出待回填）
> 范围：仅桌面端（PySide6）UI 层的绘制（painting）、图标（icons）、SVG 渲染
> 方法：架构文档（`DeepSeek Docs/01、07`）→ 逐文件逐行阅读绘制代码 → 交叉比对
> 基线：工作区 2026-08-09 状态；`git` 未 commit

## 1. 架构背景（审查依据）

- 图标统一由 `AssetsManager/core/icons.py` 的语义 SVG 注册表渲染（QSvgRenderer 离屏绘制），全部 63 处 `icons.icon()` 调用（window/menus/panels/dialogs/widgets）共用该路径；`icons.clear_cache()` 在主题切换（`themes.set_theme`/`reload_themes`）与 UI 缩放变化（`window._on_ui_scale_changed`）时被调用。
- 自绘控件清单：`panels/file_list/_grid_widget.py`（1742 行，自绘网格+纹理缓存）、`panels/image_viewer.py`、`widgets/workspace_bar.py`（自绘指示条）、`widgets/hsv_wheel.py`、`widgets/tray.py`、`dialogs/theme_preview_dialog.py`、`window.py`（背景图绘制）、`core/bg_effects.py`（模糊/马赛克）。
- 主题系统：`core/themes.py` 生成全局 QSS，`core/theme_loader.py` 热加载，`core/color_utils.py` 颜色工具。

## 2. 审查范围与覆盖

| 文件 | 结果 |
|---|---|
| `core/icons.py`、`themes.py`、`theme_loader.py`、`bg_effects.py`、`color_utils.py`、`ui_scale.py` | 全部逐行 |
| `window.py`（背景绘制/菜单/工具栏图标） | 全部逐行 |
| `dock_factory.py`、`panels/base.py` | 全部逐行 |
| `panels/file_list/_grid_widget.py`、`_base.py`、`_common.py` | 绘制路径全部逐行 |
| `panels/image_viewer.py`、`sidebar.py`、`info.py`、`tag_tree.py` | 图标与绘制路径逐行 |
| `widgets/*`（workspace_bar/hsv_wheel/tray/toast/tag_chip/stylekit/status_indicator/title_bar/command_palette/collapsible_panel/pager_overlay/elevation/lan_sharing/theme_preview） | 全部 |
| `dialogs/startup.py`、`theme_preview_dialog.py` | 绘制路径逐行 |
| 未覆盖 | `dialogs/sharing_settings_dialog.py`（2161 行，分享配置，无自绘嫌疑）、WebUI（`webui/` React，非桌面端） |

## 3. 发现清单

### A 类：确认 Bug（绘制/图标/SVG）

#### Bug 1 — `core/icons.py:113-117`：所有 SVG 图标在高 DPI 屏幕模糊（高）
`icon()` 创建 `QPixmap(pixel_size, pixel_size)` 未乘屏幕 DPR 也未 `setDevicePixelRatio()`；同库 `_grid_widget.py:1048-1050` 已正确使用 `tex.setDevicePixelRatio(dpr)`，仅 icons 遗漏。影响全部 63 处调用点，在 125%/150% 缩放 Windows 屏幕图标被软放大变糊。

修复建议：
```python
dpr = max(1.0, float(QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0))
pixmap = QPixmap(int(pixel_size * dpr), int(pixel_size * dpr))
pixmap.setDevicePixelRatio(dpr)
pixmap.fill(Qt.GlobalColor.transparent)
painter = QPainter(pixmap)
renderer.render(painter, QRectF(0, 0, pixel_size, pixel_size))
```

#### Bug 2 — `widgets/hsv_wheel.py:56-60`：HSV 色轮饱和度方向反转（高）
```python
for r in range(int(radius), 0, -1):
    sat = 1.0 - (r / radius)   # 外圈 sat=0(白)，中心 sat≈0.99(全饱和)
```
实测数值（radius=100）：r=100→sat=0.00、r=1→sat=0.99。而交互 `_update_from_pos`（:97）`saturation = dist / radius` 是中心白/边缘饱和。**显示与取色完全相反**：用户点击中心全饱和色区域，取到的却是白色。

修复：`sat = r / radius`。

#### Bug 3 — `core/bg_effects.py:25-37`：背景模糊后四边半透明暗晕（中）
`apply_blur` 将 `QGraphicsBlurEffect` 渲染到与原图等尺寸 pixmap；blur 在 item 边界外无像素可采样，模糊半径内边缘趋于透明 → 背景图四边一圈发暗发虚。

修复：先扩边（复制/镜像边缘像素）再模糊，最后裁回。

#### Bug 4 — `widgets/workspace_bar.py:214-235`：resize 后标签指示条错位（中）
`paintEvent` 用 `_indicator_pos/_indicator_width` 画底部指示条，仅 `_on_current_changed`/`add_library` 更新；窗口横向 resize 后 `tabRect()` 变化而指示条不更新 → 与选中标签错位。

修复：重写 `resizeEvent` 用 `tabRect(currentIndex())` 无动画对齐。

#### Bug 5 — `dialogs/theme_preview_dialog.py:89-94`：主题色块圆角失效（低）
先 `pixmap.fill(QColor(accent))` 填满矩形，再 `drawRoundedRect(...,3,3)` 只描边 → 角为直角；描边色 `darker(120)` 叠在填充上仅呈 1px 深色环。

修复：`fill(0)` 透明后以 `QPainterPath.addRoundedRect` + `fillPath` 填充。

### B 类：次要问题

| # | 位置 | 问题 |
|---|---|---|
| 6 | `_grid_widget.py:1362` | `cat[:4]` 截断分类文本："3D Models"→"3D M"、"Videos"→"Vide"、"Archives"→"Arch"，无省略号 |
| 7 | `window.py:153-158` | resize 防抖 150ms 期间直接绘制未缩放 `processed` 原图，大背景图拖动时每帧重绘全图（性能） |
| 8 | `themes.py:438` | `QMainWindow::separator` 无效选择器（QMainWindow 无 separator 子控件），死代码 |
| 9 | `icons.py:75` | `_ALIASES["chevron-right"]` 永不命中（`normalize()` 先 `replace("-","_")`），死代码 |
| 10 | `tray.py:59-68` | 兜底托盘图标创建时取 `themes.get()['accent']` 不再刷新 → 主题切换后颜色不更新；主题 dict 为空时 KeyError |
| 11 | `_grid_widget.py:1459` | 滚动条几何硬编码 8px，未随 `ui_scale` 缩放（`refresh_scale` 只刷 QSS 不重排几何） |
| 12 | `_base.py:1142` | 拖拽预览中 `suffix.upper()`（如 ".BLEND"）绘入 40px 图标区无省略号，易溢出 |
| 13 | `sidebar.py:41-52` | legacy emoji 映射语义错乱：🔥→"clock"、🖥→"home" |

## 4. 后续行动

- [ ] audit-1 代理：独立验证 A 类 Bug 1-5 与 B 类 8、9 的真实性
- [ ] audit-2 代理：独立验证 B 类 6、7、10、11、12、13 并补查遗漏
- [ ] 回填审计结论（VERIFIED / REFUTED / PARTIAL）与修正后的行号
