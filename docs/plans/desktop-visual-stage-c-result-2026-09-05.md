# 桌面视觉统一 · 阶段 C 结果（三发现收口）

> 状态：**STAGE RESULT（2026-09-05；已入库 commit 905f538）**
> 依据：[主报告](../reports/desktop-visual-consistency-2026-09-05.md) V03/V04/V06 节 + [阶段 B 结果](desktop-visual-stage-b-result-2026-09-05.md) §6 遗留。
> 范围约束：与并行 LAN 工作线互不接触（禁改 lan/、webui/、tests/lan/、core/file_snapshot.py）。

## 1. C-1（V03）：分享设置接入公共按钮栏

**改动**（`AssetsManager/dialogs/sharing_settings_dialog.py`、`AssetsManager/dialogs/tabbed_dialog.py`）：

- `sharing_settings_dialog._build_ui` 的 `QDialogButtonBox(Ok|Cancel)+addButton(ApplyRole)` → `DialogButtonBar()`（`tabbed_dialog.py` 新增公开别名 `DialogButtonBar = _DialogButtonBar`，避免跨模块下划线 import；仓内无既有下划线跨模块先例，别名是更干净的出口）。这是 panels/widgets/dialogs 里最后一处直接构造 QDialogButtonBox 的清理。
- 语义保持清单逐项落验（新用例 `test_button_bar_uses_shared_order_and_semantic_callbacks`）：
  - 按钮（Apply）clicked → `_apply_configuration_changes(force=True)`（断言 forced==[True]）
  - accepted → `_accept_configuration_changes`（断言触发）
  - rejected → `self.reject`（断言触发）
  - 三 variant：OK=primary / Apply=secondary / Cancel=ghost（断言 buttonVariant 属性）
  - `_dialog_apply_btn` 引用保留（grep 全库仅 dialog 内部赋值，无外部读者），同时新增 `_apply_btn` 作为 TabbedDialog 基类语言刷新契约的标准属性（基类 `_on_language_changed` 只刷 `_apply_btn`）
- 按钮顺序断言：布局顺序 Cancel | Apply | OK（对照 `test_tabbed_dialog_visuals` 既有写法，用 `layout().itemAt(i).widget()` 取实际视觉顺序）
- 语言刷新：sharing 是 TabbedDialog 子类（`_build_ui` 路径），按钮文字运行时刷新通过把栏登记为 `self._button_box` 接到基类 `_on_language_changed`；新用例 `test_button_bar_labels_refresh_on_language_change` 仿 `test_dialog_runtime_refresh` 的 monkeypatch-tr 模式断言 OK/Cancel/Apply 三键再翻译
- Enter/Esc 行为：OK 设 default（栏内置 `setDefault(True)`），Esc 由 QDialog 默认 reject 路径触发 `rejected` → `self.reject`，与标准模态框一致

## 2. C-2（V04）：网格模块级冻结常量改运行时求值

**改动**（`AssetsManager/panels/file_list/_grid_widget_render.py`、`_grid_widget_data.py`、`_grid_widget.py` docstring、`tests/desktop/test_file_list_grid_widget.py` 一处 import 迁移）：

- **未缩放设计值与运行时度量分开**（报告任务原文）：模块级只留 `_CORNER_R_D=10 / _PREVIEW_R_D=8 / _BADGE_H_D=14 / _BADGE_PAD_H_D=5`（render）与 `_CARD_PAD_D=6 / _PREVIEW_MARGIN_D=4 / _TEXT_TOP_GAP_D=5 / _TEXT_LINE_GAP_D=1`（data）
- 各自持有可重建容器：render 模块 `_RM = _GridRenderMetrics(...)`（含 `badge_r = scaled_px(themes.metrics("radius_badge"))` 派生项，保持 metrics 来源不变），data 模块 `_M = _GridMetrics(...)`；两个模块各自持有、各自重建（消费面分布决定，避免 data↔render 循环 import——render 已 import data）
- **重建点**：`DataMixin.refresh_scale` 与 `refresh_theme` 开头先调 `self._rebuild_render_metrics()`（RenderMixin 静态方法，重建 `_RM`）+ `rebuild_grid_runtime_metrics()`（模块函数，重建 `_M`），**在 `_cache.clear()` 之前**——新纹理必然用新度量烘焙，旧缓存已失效
- 所有消费点改容器取值：render 17 处 `_RM.corner_r/preview_r/badge_r/badge_h/badge_pad_h` + 4 处 `_M.preview_margin/text_top_gap/text_line_gap`；data 15 处 `_M.*`；既有测试 `_PREVIEW_MARGIN` import 改 `_M.preview_margin`
- **`_CORNER_R` 的 10 不改 `themes.prop("border_radius","md")` 派生**：实测 24 主题 `border_radius.md` 全部 =10（`assets/themes/*.json` 逐文件核对，Counter({10: 24})）。按"视觉零漂移优先"保持字面 10 并注释理由——派生式在主题改变 md 值的瞬间会改变网格卡片视觉，阶段 D 做显式校准后再派生。`_BADGE_R` 维持 `metrics("radius_badge")` 派生（本就是 metrics 源，且 24 主题无 metrics 覆盖）
- **新用例** `test_grid_scale_round_trip_restores_metrics_and_texture_identity`：1.0→1.5→1.0 往返（直接调 `widget.refresh_scale()`——独立网格 widget 不挂 bus，真实链路是 `FileListPanel._on_ui_scale_changed → grid.refresh_scale`；设置键与 bus 信号按 settings_dialog 模式同步）。断言：1.5 时 `_M.card_pad==9`、`_RM.corner_r==15`、1.5 纹理字节 != 1.0 纹理字节（同尺寸不同像素——冻结常量在修复前这里必然相等，即回归锁）；回落后 `_M == base`、`_RM == base`、往返后纹理 `toImage()` 与首帧全等
- **截图基线零漂移**：`tests/desktop/test_visual_baseline_a.py`（grid_navy/grid_dawn/details_navy）9/9 通过——ui_scale=1.0 下设计值不变，摘要 hash 不变，**未再生基线**（`visual_baseline_digests.txt` 无改动，git status 确认）

## 3. C-3（V06）：零值/尺寸规则例外收口（最小集）

### 3.1 elevation 零偏移（`AssetsManager/widgets/elevation.py:46` 附近）

- 语义确认：`_LEVELS` 三个深度的 `offset_x` 全部为 0（对称环境光阴影），`offset_y` 4/8/12 是有意的下沉量。修法按"零值短路"：`offset_x if offset_x == 0 else scaled_px(offset_x)`——未来若某深度定义非零水平偏移仍走缩放，不破坏参数化
- `scaled_px(0)` 的 max(1,...) 陷阱用新用例 `test_elevation_zero_horizontal_offset_stays_zero_under_scale` 锁定：monkeypatch 1.5 缩放，断言三个深度 `xOffset()==0.0`、`yOffset()>0`、`blurRadius()>0`

### 3.2 QuickTagger 关闭按钮热区（`AssetsManager/widgets/quick_tagger_overlay.py:147`）

- 三浮层对比：QuickLookOverlay 关闭按钮 = `metrics("hit_area")=24` × `icon_sm=16`（token 式）；QuickTagger = 手写 22×22/图标12；CommandPalette 无关闭按钮（纯 Esc）。同语义图标按钮不一致 → 对齐 QuickLook 的 token 取值（22→24 热区、12→16 图标，均为 a11y 热区下限方向）
- 改为 `scaled_px(themes.metrics("hit_area")) / scaled_px(themes.metrics("icon_sm"))`，按钮升为 `self._close_btn`（QuickLook 同名属性，测试可及）
- 新用例 `test_quick_tagger_close_button_matches_token_hit_area` 断言热区/图标尺寸等于当前 token 值

### 3.3 8pt 密度特例判定（B 阶段遗留 3 处）

- **判定**：24 主题的 `font_size` 表全库核对——token 值域 {caption:11, lg:14, md:13, sm:12, xl:16, xs:10, xxl:22, xxs:9}，**无任何主题定义 ≤8 的字号**；metrics 无主题覆盖。语义 token 最小档 xxs=9 无法表达网格副标题/角标的 8pt 密度档
- **结论**：`_grid_widget_data.py` 的 `_font_sub`/`_font_badge` 3 处 8pt 维持手写（B 阶段已注"grid density special case"），本判定记录于本文档；是否引入 xxs-2=8 token 留待阶段 D 实机密度校准，不机械替换数字（阶段 A 草案原则）

## 4. 验证记录（2026-09-05，验证于入库前工作树）

- C-1 靶向：`test_sharing_settings_dialog + test_dialog_runtime_refresh + test_tabbed_dialog_visuals` → **39 passed**（含 2 个新用例）
- C-2 靶向：`test_file_list_grid_widget + test_file_list_grid_a11y + test_file_list_details + test_file_list_view + test_visual_baseline_a` → **281 passed**（含 1 个新用例；截图摘要零漂移）
- C-3 靶向：`test_tabbed_dialog_visuals + test_quick_look_overlay + test_quick_tagger_overlay + test_command_palette` → **22 passed**（含 2 个新用例）
- 全套：`pytest tests/desktop` → **844 passed** ×2 连跑（基线 839 + 5 个新用例；main_window_empty 的 xdist 偶发时序二态复现 1 次后按已知预存 flake 隔离定性，串行复跑绿）；`pytest tests/unit tests/integration` → **2715 passed, 17 skipped**（基线持平）；ruff 我方 12 个改动/新增文件全绿（残留 21 个 error 全在 docs/reports/*evidence 脚本与 lan/zip_sources.py——并行 LAN 工作线的禁改文件，预存非本轮引入）；pyright 我方 0 error（残留 1 个 error 同在 lan/zip_sources.py，同前述）；三样式门禁 0 violations/94 files、0 legacy、inline 232/39 基线持平；check_documents 通过
- **字体清单再生**：`font-usage-inventory.json` 用 `FONT_INVENTORY_UPDATE=1` 再生 2 次——差异仅为 `_grid_widget_*` 三文件 QFont 条目的行号平移（C-2 度量容器代码插入所致），(file, role_hint, value) 三元组逐项核对零变化；理由记录于此（该棘轮的既定流程）

## 5. 棘轮与残留

| 事项 | 状态 |
|---|---|
| QDialogButtonBox 直接构造（panels/widgets/dialogs） | ✅ 0 处（本次清理最后一处） |
| 网格缩放往返 | ✅ 度量+纹理全恢复（新回归锁） |
| 浮层关闭按钮热区 | ✅ QuickTagger/QuickLook 同 token；CommandPalette 无关闭按钮不适用 |
| 8pt 特例 | 判定维持手写（§3.3），阶段 D 校准 |
| `_CORNER_R`→border_radius.md 派生 | 24 主题全 =10，保持字面+注释，阶段 D 决定 |
| V05 浮层外壳 / V06 图形尺寸-热区-控件高度三分法余量 / V06 大缩放裁字 | 阶段 D（主报告任务清单后续项） |

## 6. 证据时效性说明（审查轮 RV2 补记，2026-09-06）

`screenshots/manifest.json` 的 `source_head` 混有两个值：`112483c8`（阶段 A 初生成 8 张）与 `7d07098a`（阶段 B 空库禁用色再生 1 张）。其后阶段 B 的焦点 2px 与阶段 C 的网格度量重建均为**摘要棘轮实测零漂移**的改动，按再生成策略（"漂移即再生，零漂移不强制"）未重生成 PNG——即当前入库的 9 张 PNG 对应阶段 A/B 时期的渲染，但每次后续改动都经摘要棘轮验证"当前渲染与入库 PNG 逐行等价"。例外记录：阶段 B 再生空库 PNG 一次（V02 禁用色预期变化）；阶段 C 网格两张截图（grid_navy/grid_dawn）与阶段 A 期差异为零。**审查轮 RV1 发现并修复的 `_M` 快照缺陷（bab8b46）不改变 ui_scale=1.0 下的渲染值**，PNG 无需再生成。

无证据即 unverified——本文档自身也是这个纪律的适用对象。
