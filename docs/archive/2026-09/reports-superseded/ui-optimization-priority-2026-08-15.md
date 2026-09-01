# 桌面端 UI 优化优先级清单（2026-08-15）

> 范围：桌面端（PySide6）界面优化，聚焦**视觉一致性（主题 token 纪律）** + 前两轮审计遗留的功能性接线缺口。
> 方法：基于现有审计文档（`ui-rendering-audit-2026-08-10.md` 13 渲染 bug 已修、`desktop-fine-scan-2026-08-11.md` 100 项已修）之上，重新扫描当前 `panels/*`、`widgets/*`、`dialogs/*`、`window.py`、`core/themes.py`、`widgets/stylekit.py`。
> 结论先行：**两轮历史审计已把渲染 bug / 性能 / 崩溃类问题基本清零**，本轮新发现集中在「同一视觉元素用了多套颜色体系 / 魔法常量未集中 / 主题缩放不一致」这一类**观感统一**问题，外加 2 个跨面板功能缺口。

---

## P0 · 视觉一致性（小而快，直接提升观感统一）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| P0-1 | `_common.py:23-32` vs `_grid_widget.py:1381-1392` | **分类颜色双轨制**：`CATEGORY_BADGE_COLORS` 用固定 hex（`#2f7aa3`/`#3f8c69`/`#6f5a92`…，不随主题变）；同一网格的 `_ext_name_color` 却用主题 token（`success`/`accent`/`warning`）。同一分类（3D/Archive）徽章底色与文件名后缀色不一致，且徽章色在深/浅主题下都不适配 | 收敛为一套：分类色改走主题语义 token（或新增 `category_*` token），`CATEGORY_BADGE_COLORS` 改为 token 映射 |
| P0-2 | `_grid_widget.py:1389` | 视频分类色硬编码 `QColor("#c480d4")`（注释 "no theme equivalent"）。G1-2a 视频首帧缩略图落地后视频更显眼，此非主题色更突兀 | 主题新增语义 token（如 `video`/`category_video`）或复用现有 token；删除 hardcode |
| P0-3 | `lan_sharing.py:45`、`sharing_settings_dialog.py:756/758/1046/2064/2142`、`tag_style_dialog.py:102`、`lan/routes/system.py:69` | **魔法默认值 `#5b7ff5`**（LAN 主题色默认）在 4 个文件 8 处重复，跨桌面+LAN | 提升为单一定义（如 `core/constants.py` 的 `DEFAULT_LAN_THEME_COLOR`），四处引用 |
| P0-4 | `tag_chip.py:34-35` vs `tag_style_dialog.py:129-133` | 标签前景「对比色」helper 重复实现（lightness>160 → 黑/白），两份逻辑 | 提取公共 `contrast_on(color)` 到 `color_utils.py`，两处复用 |
| P0-5 | `window.py:428/451` | 状态标签 QSS `padding: 0 8px` 裸像素，未走 `scaled_px`（同文件 font-size 已用 `scaled_pt`） | 改 `scaled_px(8)`，与全局缩放对齐 |

---

## P1 · 功能缺口（跨面板接线，属「界面不完整」而非纯视觉）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| P1-6 | `tag_tree.py:205`（P7） | 标签树点击文件行 `emit directory_selected` 但**全应用无消费者**（`window.py:409` 只连了 `sidebar.directory_selected`），点击无导航效果 | `window.py`/`dock_factory` 接线 `tag_tree.directory_selected → file_list.navigate_to` |
| P1-7 | `tag_tree.py:380-381`（P8） | `get_tag_filter()` 无消费方，标签过滤开关点了无效（树不过滤、文件列表不过滤） | 跨面板下发 tag 过滤到 file_list（或先下线该 UI 以免误导） |

> 注：P1-6/P1-7 是 08-11 精细扫描的「明确不在本批」项，跨面板接线需 window/dock_factory 协调，属功能闭环而非纯样式，单独排期。

---

## P2 · 细节一致性 / 债清理（低优先）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| P2-8 | `plugin_manager_dialog.py:114-131/252-286` | 主题 token fallback hex 与主题实际默认不一致（`.get("danger","#e74c3c")` vs 主题默认 `#f44336`；`success` 用 `#2ecc71` vs `#4caf50`）。实际是死代码 fallback（合法主题总含全部必需 token），但误导后续维护 | 统一 fallback 为 `themes.py` 的 `_EXTENDED_FALLBACKS` 同源值或直接删冗余 fallback |
| P2-9 | 全仓 ~40 处 `StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)` | 每个方法内重复实例化（如 `info.py` 内 10 处、`sharing_settings_dialog.py` 内 13 处），功能正确但可 DRY | 模块级 `sk` 单例（`from_theme` 已是动态解析，线程安全） |
| P2-10 | `tag_tree.py:65/138` | 新增标签按钮有 `setAccessibleName` 无 `setToolTip`（同面板其它按钮均有 tooltip） | 补 `setToolTip(tr("tagtree.new_tag"))` |

---

## 基线（无需重做，供参考）

- **`ui-rendering-audit-2026-08-10.md`**：13 项渲染/图标/SVG bug（icons DPR 模糊、HSV 色轮反转、背景模糊暗晕、workspace 指示条错位、主题色块圆角、`cat[:4]` 截断、resize 全图重绘、无效 QSS、托盘图标、滚动条 8px、拖拽后缀裁切、emoji 映射）——**全部已修**。
- **`desktop-fine-scan-2026-08-11.md`**：100 项（3 高/35 中/62 低）——**已修 96 项**；残余 P7/P8（即本清单 P1-6/P1-7）、W4 残余（lan_sharing 重启重复确认）、D8 残余（share_link_dialog worker 清理）为非视觉项。
- 本轮扫描确认的主题基础设施已较完善：`core/themes.py`（token + 全局 QSS + `set_button_variant` 语义按钮）、`widgets/stylekit.py`（`label_css`/`state_css`/`dialog_css`/动画降级）、`core/ui_scale.py`（`scaled_px`/`scaled_pt`）、语义图标色 token（`icon_*`）。**固定尺寸、字体缩放、tooltip/accessibleName 覆盖均已基本达标**（`setFixedSize` 全走 `scaled_px`；面板 tooltip 覆盖良好）。

---

## 建议执行顺序

1. **P0 全部**（5 项，均为单文件/常量级改动，可一批提交）——观感统一性价比最高。
2. **P1-6 / P1-7**（跨面板接线，单独排期，先确认是否要「标签过滤」还是先下线该入口）。
3. **P2**（债清理，随下次触碰相关文件时顺带）。
