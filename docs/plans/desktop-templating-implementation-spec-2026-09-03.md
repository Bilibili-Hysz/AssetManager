---
title: "桌面端视觉模块模板化实施任务规格书 (Parallel Session Task Spec)"
type: spec
status: ACTIVE
date: 2026-09-03
area: desktop-ui / templating
owner: Antigravity Architecture Team
dependencies:
  - docs/plans/desktop-ui-unification-audit-2026-09-03.md
  - AssetsManager/panels/base.py (StandardPanel)
  - AssetsManager/widgets/empty_state.py (EmptyStateWidget)
  - AssetsManager/dialogs/modal_dialog.py (StandardModalDialog)
---

# 桌面端视觉模块模板化实施任务规格书

> **目的**：指导外部/并行智能体会话独立、安全、零冲突地推进“桌面端全域视觉模块模板化与设计系统 2.0 收口”工作。  
> **前置事实基准**：M2.1 基础设施（`StandardPanel`、`EmptyStateWidget`、`StandardModalDialog`）已完成并合入代码库，全量 753 个测试与 7 大质量门禁全绿。

---

## 一、 并行任务拆分与隔离边界

为了保证多个会话并行开发时不发生 Git 冲突，任务严格划分为 **两个完全隔离的工作包 (Tracks)**：

| 任务包 | 责任领域 | 涉及文件（严格隔离） | 核心目标 |
|---|---|---|---|
| **Track A** | **业务面板插槽化与方言清零** | `panels/sidebar.py`<br>`panels/tag_tree.py`<br>`panels/file_list/_base_layout.py`<br>`widgets/workspace_bar.py`<br>`scripts/style_dialect_ledger.json` | 1. 侧边栏与标签树接入 `StandardPanel`<br>2. 45 处 `t[...]` 裸字典方言全部清零<br>3. G3 门禁升级为零容忍 |
| **Track B** | **弹窗体系收编为 StandardModalDialog** | `dialogs/color_picker_dialog.py`<br>`dialogs/tag_style_dialog.py`<br>`dialogs/plugin_operator_dialog.py`<br>`dialogs/generic_settings_dialog.py`<br>`dialogs/sidebar_settings_dialog.py`<br>`dialogs/theme_preview_dialog.py`<br>`panels/file_list/_batch_rename_dialog.py` | 1. 原生 QDialog 迁入 `StandardModalDialog`<br>2. 消除手排 OK/Cancel 按钮行<br>3. 接入窗口记忆与缩放 |

---

## 二、 Track A 任务规格：业务面板插槽化与方言清零

### 1. 目标
将 `SidebarPanel` 与 `TagTreePanel` 由原本在 `content_layout` 中随意拼接的模式，重构为标准的 `StandardPanel` 插槽契约；同时清零全库挂账的 45 处 `t[...]` 旧式字典方言。

### 2. 详细改造指导

#### A1. `SidebarPanel` (`AssetsManager/panels/sidebar.py`)
* 改为继承 `StandardPanel`；
* 将原本的搜索框与折叠按钮栏装入 `self.set_toolbar(toolbar_widget)`；
* 将 `self._tree` 装入 `self.set_body(self._tree, stretch=1)`；
* 将底部的 `self._status_bar` 装入 `self.set_footer(self._status_bar)`；
* 原本散落手绘的 `self._empty_state` 替换为基类的 `self.show_state("directory")` / `self.clear_state()`；
* 消除内部 4 处 `t[...]` 访问，改为 `sk.token(...)` 或 `themes.color(...)`。

#### A2. `TagTreePanel` (`AssetsManager/panels/tag_tree.py`)
* 改为继承 `StandardPanel`；
* 顶部搜索框与新建标签按钮栏接入 `self.set_toolbar(bar)`；
* 树视图接入 `self.set_body(self._tree, stretch=1)`；
* 消除内部 1 处 `t[...]` 访问。

#### A3. 45 处方言清零 (`scripts/style_dialect_ledger.json`)
逐一查看账本中的 9 个文件，将其中的 `t[...]` 转换为规范 API：
- `startup.py` (25 处)
- `sidebar.py` (4 处)
- `plugin_ui.py` (4 处)
- `workspace_bar.py` (3 处)
- `window_coordinator.py` (3 处)
- `_base_layout.py` (2 处)
- `lan_sharing.py` (2 处)
- `tag_tree.py` (1 处)
- `window.py` (1 处)
* 转换原则：
  * 在有 StyleKit 实例处使用：`sk.token("token")`, `sk.alpha("token", ...)`, `sk.lighter("token", ...)`, `sk.darker("token", ...)`；
  * 在无 StyleKit 实例处使用：`themes.color("token")`, `themes.prop(...)`。
* 运行 `python scripts/check_style_dialects.py --update`，确认方言计数归零！

---

## 三、 Track B 任务规格：弹窗体系收编为 StandardModalDialog

### 1. 目标
消灭全库 8 个原生 `QDialog` 的粗糙排版、硬编码固定尺寸与手工构建的按钮行，全面继承 [`StandardModalDialog`](file:///d:/~Vibe-Coding/Projects/AssetsManager_old-bak/AssetsManager/dialogs/modal_dialog.py)。

### 2. 详细改造指导

#### B1. 对话框迁移清单与规范
1. **`AssetsManager/dialogs/color_picker_dialog.py`** (`ColorPickerDialog`)
   * 改为继承 `StandardModalDialog`；
   * 实现 `setup_content(self, layout: QVBoxLayout)` 放置色板网格与滑块；
   * 删除本地手工添加的 `ok_btn` 与 `cancel_btn` 按钮行（由模板自动托管）。
2. **`AssetsManager/dialogs/tag_style_dialog.py`** (`TagStyleDialog`)
   * 改为继承 `StandardModalDialog`；
   * 实现 `setup_content(layout)` 放置颜色/形状选择器；
   * 删除本地手工按钮行。
3. **`AssetsManager/panels/file_list/_batch_rename_dialog.py`** (`_BatchRenameDialog`)
   * 改为继承 `StandardModalDialog`；
   * 移除写死的 `resize(620, 400)`，指定 `min_size=(scaled_px(620), scaled_px(400))`；
   * 实现 `setup_content(layout)`，接入模板主按钮。
4. **`AssetsManager/dialogs/generic_settings_dialog.py`**
   * 改为基于 `StandardModalDialog` 的简洁轻弹窗。
5. **`AssetsManager/dialogs/plugin_operator_dialog.py`**
   * 继承 `StandardModalDialog`，接管按钮状态与结果回调。
6. **`AssetsManager/dialogs/sidebar_settings_dialog.py`**
   * 规范化按钮与设置项排版。

---

## 四、 统一验证纪律与验收清单

任何一个并行会话在完成任务后，必须无条件依次通过以下全部 7 项门禁验证：

```bash
# 1. 代码规范与语法检查（零警告）
python -m ruff check AssetsManager scripts tests

# 2. 样式静态源合规检查（零违规）
python scripts/check_style_sources.py

# 3. 样式调用棘轮门禁（只降不升）
python scripts/check_inline_styles.py

# 4. 方言门禁（Track A 必须归零）
python scripts/check_style_dialects.py

# 5. 分层依赖架构与取数规范检查
python scripts/check_layers.py
python scripts/check_frontend_data_fetch.py

# 6. 文档与统计指标对齐
python scripts/check_doc_stats.py --fix

# 7. 全量桌面端测试（必须全绿，允许 1 个 share 信号无关警告）
pytest tests/desktop/
```
