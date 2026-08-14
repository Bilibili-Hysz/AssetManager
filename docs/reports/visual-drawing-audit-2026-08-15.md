# 视觉 / 绘制现状审计（2026-08-15）

范围：`AssetsManager/core/themes.py`、`widgets/`、`panels/`、`dialogs/`、`window*.py`。
目标：在「柔和圆角 + 轻投影」的视觉基调下，找出**仍未打磨的组件**、**绘制性能热点**、**主题应用不一致**，给出优先级。

## 1. 已确立的视觉基线（已达标，保持不变）

- `themes.py` 全局 QSS 已 token 化：圆角/间距/字号走 `properties`，滚动条 6px 透明、按钮四变体、`border_subtle` 发丝线。
- 已打磨组件：`toast`（elevation + 阴影边距）、`collapsible_panel`（alpha/border_subtle/scaled）、`empty`（语义图标）、file_list 网格（滚动条/卡片圆角）。
- 20 主题（`assets/Themes/*.json`）已铺开 `border_radius/spacing/font_size`。

## 2. 绘制性能热点（优先级高）

| # | 位置 | 现象 | 建议 |
| --- | --- | --- | --- |
| P1 | `widgets/hsv_wheel.py:78-83` | 饱和度渐变用 `for r in range(int(radius)-1,0,-1): drawEllipse(...)`，半径 ~96px 时**每帧 ~96 次 drawEllipse**（拖动时每帧重绘） | 改为单个 `QRadialGradient`（中心白→边缘 HSV 全饱和）+ 一次 `drawEllipse`/`fillRect`，~96→1 次绘制 |
| P2 | `panels/image_viewer.py:571` 缩略图条 | 逐格 `drawPixmap`（可接受） | 若可见格数多，可复用逐格纹理缓存（同 file_list 思路），非必需 |

## 3. 未打磨组件（硬编码样式 / 缺阴影）

| # | 位置 | 现象 | 建议 |
| --- | --- | --- | --- |
| V1 | `dialogs/color_picker_dialog.py:96,204` | `border: 1px solid #555; border-radius: 4px` 硬编码（非 token、非 scaled_px） | 用 `themes.color("border")` + `scaled_px(...)` 或 `StyleKit` |
| V2 | `widgets/theme_preview.py:339-340`、`dialogs/theme_preview_dialog.py:88` | 色板 `border: 1px solid #555; border-radius: 4px` 硬编码 | 同 V1 |
| V3 | `widgets/workspace_bar.py:96-120` | 多处硬编码 `padding: 2px 8px` 等 | 改用 `scaled_px`/`StyleKit` |
| V4 | `panels/info.py:277,349` | 局部 `setStyleSheet` 混用 `sk.pt` 与硬编码 `padding: 2px 0` | 统一到 `StyleKit` |
| V5 | （已更正，非问题） | 核查后：`dialogs/` 目录下无 `FramelessWindowHint`/`Tool` 窗口，对话框均为常规 `QDialog`（由系统提供窗口阴影）；`apply_elevation` 的实际用途是给**窗口内的卡片式容器**（startup 的 detail/list panel、toast、plugin_manager）加阴影，不是给对话框 | 无需处理；如需进一步「卡片化」，可评估 info 面板/侧栏卡片是否要 elevation，属设计取舍 |

## 4. 主题应用一致性（结构性）

- 部分组件仍用**局部 `setStyleSheet` + 硬编码色值**（V1–V4），与全局 token 化 QSS 不一致，主题切换时可能漏变或色偏。
- 建议逐步把「局部硬编码样式」收敛为：优先复用全局 QSS + `set_button_variant`；确需局部的，走 `StyleKit.from_theme` / `themes.color()` / `scaled_px()`。

## 5. 建议优先级

1. **P1 hsv_wheel 饱和度渐变**（纯性能，改动小、收益直接，拖色盘时掉帧会明显改善）。
2. **V1/V2/V3 硬编码样式收敛**（低风险，视觉一致性 + 主题适配）。
3. **V5 浮动表面补 elevation**（低风险，视觉层次更「现代」）。
4. **V4 + 其余局部样式扫尾**（逐步）。

> 说明：`plugin_manager_dialog`/`theme_preview` 里的 `t.get("danger","#e74c3c")` 等**带默认值的 fallback hex** 属于正常兜底，不列为问题；真正的问题是「无 token、无 scaled 的裸硬编码」。
