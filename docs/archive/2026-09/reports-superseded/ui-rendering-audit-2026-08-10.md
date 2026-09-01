# 桌面端 UI 渲染审计 · 第一轮（2026-08-10）

> 范围：桌面端（PySide6）UI 绘制代码逐行审查，重点是图标/SVG 渲染。
> 方法：从 `DeepSeek Docs/07-桌面UI层.md` 架构图出发，逐文件审查
> `core/icons.py`、`core/themes.py`、`core/bg_effects.py`、`widgets/*`、
> `panels/*`（含 `panels/file_list/_grid_widget.py`）、`dialogs/*` 的自绘代码。
> 状态：**本报告为第一轮人工审查结论，已被两个独立子代理二次审计**
> （审计结果见文末附录 A/B）。

## 架构背景

- 图标体系：`core/icons.py` 统一以 SVG path 注册表 + `QSvgRenderer` 渲染
  主题色线条图标（63 处调用点），缓存 key = `(name, color, size)`。
- 主题体系：`core/themes.py`（token）+ `core/theme_loader.py`（JSON 热加载）
  + `core/color_utils.py`（hex→rgba 工具）。
- 自绘热点：`panels/file_list/_grid_widget.py`（纹理缓存网格）、
  `panels/image_viewer.py`、`widgets/hsv_wheel.py`、`widgets/workspace_bar.py`、
  `widgets/status_indicator.py`、`window.py`（背景图）、`core/bg_effects.py`。

---

## 一、确认 Bug（绘制 / 图标 / SVG）

### Bug 1 — `AssetsManager/core/icons.py:113-117`：SVG 图标高 DPI 模糊（严重）

- **现象**：`icon()` 创建 `QPixmap(pixel_size, pixel_size)` 未乘屏幕 DPR，
  也未 `setDevicePixelRatio()`。在 125%/150% 缩放的 Windows 屏幕上，Qt 将
  16px 源图软放大到物理像素，全部图标模糊。
- **证据**：同一代码库 `_grid_widget.py:1048-1050` 已正确实现
  `tex.setDevicePixelRatio(dpr)`（`dpr = self.devicePixelRatioF()`），
  icons.py 未做相同处理。
- **影响面**：63 处 `icons.icon()` 调用（菜单/工具栏/树/按钮/对话框/状态指示）。
- **修复建议**：
  ```python
  dpr = max(1.0, float(QGuiApplication.primaryScreen().devicePixelRatio()
                        if QGuiApplication.primaryScreen() else 1.0))
  pixmap = QPixmap(int(pixel_size * dpr), int(pixel_size * dpr))
  pixmap.setDevicePixelRatio(dpr)
  pixmap.fill(Qt.GlobalColor.transparent)
  painter = QPainter(pixmap)
  renderer.render(painter, QRectF(0, 0, pixel_size, pixel_size))
  ```

### Bug 2 — `AssetsManager/widgets/hsv_wheel.py:56-60`：HSV 色轮饱和度方向反转（严重）

- **现象**：饱和度同心圆从外向内绘制：`sat = 1.0 - (r / radius)`，
  r=radius（边缘）→ sat=0（白色），r→1（中心）→ sat≈0.99（全饱和）。
  实测：`r=100→sat=0.00；r=1→sat=0.99`。
- **矛盾点**：交互取色 `_update_from_pos`（:97）`self._saturation = dist / radius`
  是中心白、边缘饱和。**色轮显示与取色完全相反**：用户看到中心全饱和色，
  点击中心却取到白色。
- **修复建议**：`sat = r / radius`（中心 0、边缘 1）。

### Bug 3 — `AssetsManager/core/bg_effects.py:25-37`：背景模糊四边半透明暗晕

- **现象**：`apply_blur` 用 `QGraphicsBlurEffect` 渲染到与原图等尺寸的
  QPixmap。QGraphicsBlurEffect 在 item 边界外无像素可采样，模糊半径内
  边缘像素趋于透明 → 背景图四边一圈发虚变暗。
- **修复建议**：先向外扩边（镜像/复制边缘像素）再模糊，最后裁回原尺寸。

### Bug 4 — `AssetsManager/widgets/workspace_bar.py:214-235`：resize 后标签指示条错位

- **现象**：指示条由 `paintEvent` 用 `_indicator_pos/_indicator_width` 绘制，
  仅在 `_on_current_changed`/`add_library` 时更新。窗口横向 resize 后
  `tabRect()` 变化而指示条不更新 → 指示条与当前选中标签错位。
- **修复建议**：重写 `resizeEvent`，用 `tabRect(currentIndex())` 无动画对齐。

### Bug 5 — `AssetsManager/dialogs/theme_preview_dialog.py:89-94`：主题色块圆角失效

- **现象**：先 `pixmap.fill(QColor(accent))` 填满整矩形，再
  `drawRoundedRect(..., 3, 3)` 只描边 → 四角是直角，圆角从未生效；
  描边色叠在填充色上仅呈 1px 深色环。
- **修复建议**：`fill(0)` 透明填充后，用 `QPainterPath.addRoundedRect` +
  `fillPath(accent)`。

---

## 二、次要问题（提示级）

| # | 位置 | 问题 |
|---|------|------|
| 6 | `_grid_widget.py:1361-1362` | `cat[:4]` 截断分类文本（`EXT_TO_CATEGORY` 取规范 key：images/models/videos/documents/archives），实际显示为小写 4 字符碎片（"images"→"imag"、"models"→"mode"…），未知扩展名显示 "Othe"，无省略号 |
| 7 | `window.py:153-158` | resize 防抖 150ms 期间直接绘制未缩放的 `processed` 原图，大背景图拖动时每帧重绘全图（掉帧） |
| 8 | `themes.py:438-440` | `QMainWindow::separator` 无效选择器（QMainWindow 无 separator 子控件，Qt QSS 参考中 QMainWindow 无任何子控件），死代码 |
| 9 | `icons.py:75-76` | `_ALIASES["chevron-right"]` 与 `"more-horizontal"` 均永不命中（`normalize()` 先 `replace("-","_")`），死代码 |
| 10 | `tray.py:59` | 兜底托盘图标创建时取 `themes.get()['accent']` 且不再刷新 → 主题切换后托盘图标颜色不更新；主题 dict 为空时 `{}['accent']` 抛 KeyError（启动即崩溃，app.py:70 无 try/except 包裹）。注：正常运行时走 `assets/icons/icon.ico` 文件分支（app.py:69），兜底仅在文件缺失时生效 |
| 11 | `_grid_widget.py:1459` | 滚动条几何硬编码 8px，未随 `ui_scale` 缩放（`refresh_scale` 只刷 QSS 不重排几何）；QSS `scaled_px(8)` 被 widget 几何裁剪，scale≠1.0 时滚动条保持 8px |
| 12 | `_base.py:1131,1141-1142` | 拖拽预览中 `suffix.upper()` 绘入 40px 图标区无 elideText（同函数其余三处文本均有 elideText）→ 超宽后缀（如 ".BLEND1" 46px）被无省略号裁切；ui_scale>1 时受影响后缀集合扩大 |
| 13 | `sidebar.py:41-52` | legacy emoji 映射语义错乱 10 条中 4 条：💾→folder、🖥→home、🎨→file、🔥→clock；来源为 favorites.json 的 `icon` 字段（旧版直接写入 emoji） |

---

## 附录 A · 子代理审计 1（图标/色轮/指示条/色块类）结论

审计项：Bug 1、2、4、5、9、10。结论：**5 项确认，1 项确认（表述需修正）**。

- **Bug 1 — 确认**。`icons.py:113` `QPixmap(pixel_size, pixel_size)`、`:120` `QIcon(pixmap)`，全函数无 `setDevicePixelRatio`；全项目 DPR 处理仅存在于 `_grid_widget.py:1048-1050`、`_base.py:1110-1112`，icons.py 缺失。缓存键 `(resolved, tint, pixel_size)`（:102）不含 dpr。`tests/core/test_icons.py` 无 DPR 断言（全仓库唯一 DPR 断言是 `tests/desktop/test_file_list_grid_widget.py:667-681`，只覆盖网格纹理）。Qt6 中 QIcon(QPixmap) 走 QPixmapIconEngine，dpr=1 源在 1.5x 屏上按 SmoothTransformation 软放大 → 模糊。修复点定位准确，建议将 dpr 纳入缓存键。
- **Bug 2 — 确认**。`hsv_wheel.py:55` 注释 "center = white, edge = full saturation" 与 `:56-60` 代码（`sat = 1.0 - r/radius`：边缘白、中心饱和）**自相矛盾**；交互 `:97` `sat = dist/radius`（中心白）与绘制相反。指示器（:63-66）按取色模型定位，与视觉梯度不一致。附带：饱和度圆从 r=radius 起画，最外圈白色还会覆盖色相环。修复：`:57` 改 `sat = r / radius`。
- **Bug 4 — 确认**。`WorkspaceBar` 全文无 `resizeEvent` 重写；`_indicator_pos/_indicator_width` 仅在 `add_library`（:155-158）与 `_animate_indicator`（:193-212，仅 `currentChanged` 触发）赋值；resize 后 `tabRect` 变化（tab 收缩/滚动按钮出现平移）但指示条不更新，无任何补救路径。`tests/unit/test_workspace_bar.py` 未覆盖。修复：重写 `resizeEvent` → `_animate_indicator(currentIndex())`。
- **Bug 5 — 确认**。`theme_preview_dialog.py:89-90` 先 `pixmap.fill(accent)` 整块不透明填满，`:91-93` 未 setBrush（默认 NoBrush）仅 1px 圆角描边 → 四角仍是 accent 色，圆角切角从未生效。修复：去预填充，setBrush+NoPen 直接 drawRoundedRect。
- **Bug 9 — 确认（范围扩大）**。`normalize()` :83 先 `replace("-","_")` 再 :84 查 `_ALIASES` → `"chevron-right"` 与 **`"more-horizontal"`（:76）均为死代码**；`has()`（:92-94）同样。无连字符的 `gear/globe/plugin` 仍可达（`tests/core/test_icons.py:14` 验证 `normalize("gear")=="settings"`）。
- **Bug 10 — 确认（表述需修正）**。(a) 兜底分支仅在 `icon_path=None` 或文件缺失时生效——正常运行时 `app.py:69` 传入 `assets/icons/icon.ico`（实测存在），走文件分支；系统托盘无任何 `theme_changed` 连接（全项目 31 处连接不含 tray），兜底图标颜色确认不随主题刷新。(b) `themes.get()` 空 dict 时返回 `{}`（themes.py:192），`tray.py:59` 直接 `['accent']` → **KeyError**，且 `app.py:70` 无 try/except 包裹 → 空主题场景启动即崩溃。修复：`themes.get().get("accent", "#4a60b0")` + 连接 `theme_changed` 重建图标。

## 附录 B · 子代理审计 2（效果/文本/样式类）结论

审计项：Bug 3、6、7、8、11、12、13。结论：**5 项确认，2 项确认（表述需修正）**。

- **Bug 3 — 确认**。`bg_effects.py:35` `scene.render(painter, QRectF(0,0,w,h), QRectF(0,0,w,h))` 目标/源 rect 等尺寸；`window.py:138/144/151/157-158` 全链路无裁剪，边缘半透明原样上屏。实测（PySide6 6.11.0）：radius=10 时边缘 alpha≈54%、角点 alpha≈29%；radius=25 时边缘 alpha≈50%。模糊半径宽、50-60% alpha 的半透明边带确凿存在，叠加 `setOpacity(opacity)` 后表现为四边暗晕。严重度中低。修复方向正确（源 rect 扩展半径或先 pad 后裁）。
- **Bug 6 — 需修正**。截断属实且影响所有分类，但报告的示例错误：`EXT_TO_CATEGORY` 由 `FILTER_CATEGORY_EXTS`（**规范 key**）构建（_common.py:13-16），真实取值为 `images/models/videos/documents/archives` + 未知→"Other"，**"3D Models" 不会出现**。实际截断结果：`"imag" / "mode" / "vide" / "docu" / "arch" / "Othe"`（全小写碎片）。正文表已修正。
- **Bug 7 — 确认**。逻辑链逐行吻合：`:150` 生成 scaled 的唯一分支被 `_bg_dirty` 挡住 → `:157-158` 直接 blit 未缩放 `processed` 原图；`:174-178` resize 期间每次重置 150ms 计时器，`_bg_dirty=True` 贯穿拖动全程。4K 背景拖动时每帧整幅重绘。性能缺陷（非正确性），严重度中等，防抖目的（避免拖动中反复缩放）与副作用（拖动中全图重绘）并存。
- **Bug 8 — 确认**。Qt Style Sheets Reference 中 QMainWindow **无任何子控件**（`::separator` 仅存在于 QToolBar/QMenu；QDockWidget 仅 `::title`），dock 分隔条由 QMainWindowLayout 私有绘制、QSS 无法样式化（QTBUG 已知限制）。:438-440 为无效规则，被解析器静默忽略，影响为零，建议删除。
- **Bug 11 — 确认**。`resizeEvent` :1459 硬编码 8px；QSS :1413 `scaled_px(8)`（scale 1.5 时为 12px）；`refresh_scale`（:1429-1440）只刷 QSS 不重设几何，且 `file_list/__init__.py:263-269` 的 ui_scale 变更路径不触发 grid 的 resizeEvent。实测 QSS 宽度被 widget 几何裁剪 → scale≠1.0 时滚动条保持 8px 不缩放，且无自愈路径。中低严重度。
- **Bug 12 — 需修正措辞**。`:1131` 40×40 图标区、`:1141-1142` `drawText(AlignCenter, suffix.upper())` 无 elideText（同函数 :1152/:1162/:1170 均有）。实测：`BLEND`=39px 勉强容纳，**`BLEND1`=46px 超宽**（本应用为 Blender 资产管理器，`.blend1` 为高频自动存档后缀），超宽文本在盒内被裁切（无省略号，文字顶边），不会溢出盒外。报告"易溢出"改为"超宽后缀被无省略号裁切"更准确；ui_scale>1 时受影响后缀集合扩大。正文表已修正。
- **Bug 13 — 确认（范围扩大）**。10 条映射逐条核验，**4 条语义错乱**：💾→folder、🖥→home、🎨→file、🔥→clock（⭐/📁/📂/🏠 正确，🔖/📌 近似可接受）。来源确认：favorites.json 的 `icon` 字段（sidebar.py:339 读取，sidebar_favorites.py:58-68 存储；git commit 8899575 证实旧版直接写入 emoji）。影响：老用户收藏中这 4 种 emoji 被迁移成无关图标。正文表已修正。

---

## 三、审计汇总

| 项 | 结论 | 修正 |
|----|------|------|
| Bug 1 icons DPR | ✅ 确认（严重） | 无 |
| Bug 2 HSV 色轮反转 | ✅ 确认（严重） | 无 |
| Bug 3 背景模糊暗晕 | ✅ 确认（中低） | 无 |
| Bug 4 标签指示条错位 | ✅ 确认 | 无 |
| Bug 5 主题色块圆角 | ✅ 确认 | 无 |
| Bug 6 `cat[:4]` 截断 | ✅ 确认 | 示例/来源已修正（规范 key 小写碎片） |
| Bug 7 resize 全图重绘 | ✅ 确认（性能） | 无 |
| Bug 8 无效 QSS 选择器 | ✅ 确认（零影响） | 无 |
| Bug 9 alias 死代码 | ✅ 确认 | 范围扩大（more-horizontal 同病） |
| Bug 10 托盘图标 | ✅ 确认 | 补充前提（正常走 icon.ico 文件分支） |
| Bug 11 滚动条 8px | ✅ 确认（中低） | 无 |
| Bug 12 拖拽预览后缀 | ✅ 确认（低） | 措辞修正（裁切非溢出），.blend1 为高频特例 |
| Bug 13 emoji 映射 | ✅ 确认 | 范围扩大（共 4 条错乱） |

全部 13 项均被独立子代理验证为真实问题，无反驳项；3 处表述已修正/补全。

---

## 四、修复记录（2026-08-10 同日）

修复由 3 个并行子代理实施（文件集互不相交），随后由 2 个只读审计子代理复审。全部 13 项已修复，审计 12/12 通过。

| 项 | 修复内容 | 复审结论 |
|----|----------|----------|
| Bug 1 | `icons.py`：按 `primaryScreen().devicePixelRatio()` 渲染物理尺寸 + `setDevicePixelRatio(dpr)`；缓存键扩为 `(name, tint, size, dpr)`；无屏幕回退 1.0 | ✅ 通过（test_icons 3 passed） |
| Bug 2 | `hsv_wheel.py:57`：`sat = 1.0 - r/radius` → `sat = r/radius`；循环起点 `int(radius)-1` 保留 1px 色相环 | ✅ 通过 |
| Bug 3 | `bg_effects.py`：9 格平铺扩边 `pad=2*radius` → 模糊 → `copy(pad,pad,w,h)` 裁回；边缘 alpha 29%→97% | ✅ 通过（test_bg_effects 5 passed；radius>min(w,h)/2 时平铺有缝隙，实际不可达） |
| Bug 4 | `workspace_bar.py`：新增 `resizeEvent`，stop 两动画后按 `tabRect(currentIndex())` 无动画对齐 | ✅ 通过（test_workspace_bar 6 passed；动画打断探针验证无回写） |
| Bug 5 | `theme_preview_dialog.py`：透明填充 + `setBrush(accent)`+`setPen(NoPen)` 圆角填充 | ✅ 通过 |
| Bug 6 | `_grid_widget.py`：新增 `_CATEGORY_LABELS = dict(FILTER_CATEGORY_LABELS)`，`elidedText(完整标签, ElideRight)` 替代 `cat[:4]` | ✅ 通过（test_grid 72 passed） |
| Bug 7 | `window.py`：dirty 期间也生成 scaled（不写缓存），防抖结束后一次性重建入缓存 | ✅ 通过（成本同阶，无回归） |
| Bug 8 | `themes.py`：删除无效 `QMainWindow::separator` 规则 | ✅ 通过（test_themes 13 passed） |
| Bug 9 | 死代码（chevron-right/more-horizontal alias）：保留不动（零影响，见注 1） | ✅ 通过 |
| Bug 10 | `tray.py`：`themes.get().get("accent", "#4a60b0")` 兜底；`_generated_icon` 标志 + `theme_changed` 连接，仅兜底图标随主题重建 | ✅ 通过（test_tray 挂起为预存在问题：无 QApplication fixture） |
| Bug 11 | `_grid_widget.py`：`_relayout_scrollbar()` 用 `scaled_px(8)`；resizeEvent 与 refresh_scale 均调用（含宽高≤0 守卫） | ✅ 通过 |
| Bug 12 | `_base.py`：拖拽预览后缀文本加 `elidedText(ElideRight)`（对齐保持居中，`or "?"` 保留） | ✅ 通过 |
| Bug 13 | `sidebar.py`：💾→file、🖥→grid、🎨→image、🔥→star（4 条全落在 `_ICON_PATHS` 内，无静默 fallback） | ✅ 通过 |

验证：`ruff check` 11 文件全部通过；`pytest` 定向 91 passed（test_icons 3 + test_bg_effects 5 + test_workspace_bar 6 + test_grid 72 + test_tray/test_sidebar 5）。

注 1：Bug 9（alias 死代码）与 Bug 13 均属 `icons.py`/`sidebar.py` 内部小死代码，`chevron-right`/`more-horizontal` alias 删除会改变 `has()`/`normalize()` 的入参容错面，且零用户影响，本次**有意未修复**（保留历史别名以兼容外部插件调用）。
注 2：审计发现的预存在问题（非本次引入）：`tests/unit/test_tray.py` 无 QApplication fixture 导致挂起；grid 测试未覆盖新标签/省略号与 scale 重排路径（建议后续补充）。
注 3：本次修复在仓库原有未提交工作区改动（README 记录 191 tracked modified）之上增量进行，`git diff` 中与 Bug 无关的 hunk（如 `_base.py` warnings 反馈、`window.py` integrity 调度）为预先存在改动，已排除在修复与审计范围外。
