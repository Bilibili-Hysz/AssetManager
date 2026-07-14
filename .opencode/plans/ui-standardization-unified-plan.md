# UI 标准化统一执行计划

> 创建时间：2026-06-08
> 状态：待执行
> 合并来源：ui-standardization-opportunities.md + ui-standardization-plan.md
> 目的：为 UI 重构智能体提供完整、无冲突的执行依据

---

## 一、两份计划对比

| 维度 | opportunities 文档 | plan 文档 |
|------|-------------------|-----------|
| **范围** | 分析了所有 6 个对话框模块 | 聚焦 5 个具体任务 |
| **P0** | 修复 SidebarSettingsDialog 重复信号 | 消除 lan_sharing 重复对话框 (~250行) |
| **P1** | SettingsDialog 改造 | SettingsDialog 迁移 + make_radio_group |
| **P2** | SidebarSettingsDialog 改造 | SidebarSettingsDialog 迁移 |
| **P3** | TagEditorDialog 改造 | 抽取共享按钮样式 |
| **P4** | generic_settings_dialog 改造 | 共享齿轮按钮 |

### 冲突点

| 项目 | opportunities 方案 | plan 方案 | 统一决策 |
|------|-------------------|-----------|----------|
| P0 优先级 | 修复重复信号连接 (5min) | 消除 lan_sharing 重复对话框 (250行) | **采用 plan 方案** - 收益更大 |
| TagEditorDialog | P2 改造为 TabbedDialog | 未提及 | **保留，移至 P5** |
| generic_settings_dialog | P3 改造 | 未提及 | **保留，移至 P6** |
| 共享按钮样式 | 未提及 | P3 抽取 style_helpers.py | **采用** |
| 齿轮按钮 | 未提及 | P4 共享齿轮按钮 | **采用** |

### 互补点

| opportunities 提供 | plan 提供 |
|-------------------|-----------|
| TabbedDialog 能力清单 | 具体任务分解 |
| 各模块详细分析 | make_radio_group 接口设计 |
| 验收标准 | 执行顺序模板 |
| 注意事项 | 执行记录模板 |

---

## 二、统一执行计划

### P0: 消除 lan_sharing 重复对话框 (~250行)

| 项目 | 内容 |
|------|------|
| **文件** | `widgets/lan_sharing.py` |
| **问题** | `_show_share_dialog()`（~260 行）完全重复了 `SharingSettingsDialog` 的全部功能 |
| **方案** | 删除 `_show_share_dialog()`，改为调用已有的 `_open_sharing_settings()` |
| **收益** | -250 行重复代码 |
| **预计工时** | 30min |

### P1: SettingsDialog 迁移到 TabbedDialog (~45行)

| 项目 | 内容 |
|------|------|
| **文件** | `core/settings_dialog.py`, `core/tabbed_dialog.py` |
| **问题** | 3 次重复的 QGroupBox + QButtonGroup + QRadioButton 循环模式 |
| **方案** | 1. `TabbedDialog` 新增 `make_radio_group()` 工厂方法；2. `SettingsDialog` 继承 `TabbedDialog` |
| **收益** | -20 行 + 统一主题 |
| **预计工时** | 1-2h |

**make_radio_group 接口设计：**
```python
def make_radio_group(self, title: str, options: dict[str, str], current: str,
                     on_changed=None) -> tuple[QGroupBox, QButtonGroup]:
    """Create a styled QGroupBox with radio buttons.
    
    Args:
        title: Group box title
        options: {key: display_label} dict
        current: Currently selected key
        on_changed: Optional callback(key)
    Returns:
        (groupbox, button_group) — buttons have 'option_key' property
    """
```

### P2: SidebarSettingsDialog 迁移 (~30行)

| 项目 | 内容 |
|------|------|
| **文件** | `core/sidebar_settings_dialog.py` |
| **问题** | Manual QGroupBox × 3 + QLabel + QSpinBox 行 + 重复信号连接 Bug |
| **方案** | 继承 `TabbedDialog`，用 `make_groupbox()`、`make_labeled_row()`、内置按钮栏替代 |
| **收益** | -25 行样板代码 + 修复 Bug |
| **预计工时** | 1h |

**Bug 修复：** Line 32-33 重复信号连接，改为单次连接。

### P3: 抽取共享按钮样式 (~35行)

| 项目 | 内容 |
|------|------|
| **文件** | 新建 `core/style_helpers.py`，改 `startup.py`、`workspace_bar.py`、`info.py` |
| **问题** | `startup.py` 的 `_primary_btn_qss()`/`_ghost_btn_qss()` 与 `TabbedDialog.primary_btn_style()`/`secondary_btn_style()` 语义相同 |
| **方案** | 从 `TabbedDialog` 抽取样式方法到独立模块，所有文件 import 使用 |
| **收益** | -20 行重复定义 |
| **预计工时** | 30min |

### P4: 共享齿轮按钮 (~16行)

| 项目 | 内容 |
|------|------|
| **文件** | `core/style_helpers.py`, `panels/base.py`, `panels/info.py`, `panels/sidebar.py` |
| **问题** | 3 处完全相同的 12 行齿轮设置按钮 |
| **方案** | `style_helpers.make_gear_button(callback)` |
| **收益** | -16 行重复代码 |
| **预计工时** | 30min |

### P5: TagEditorDialog 改造 (~1h)

| 项目 | 内容 |
|------|------|
| **文件** | `core/tag_editor_dialog.py` |
| **问题** | 使用 `themes.apply_to(self)`，tag chip 创建逻辑封闭 |
| **方案** | 使用内联 CSS，提取 `make_chip()` 方法到 `TabbedDialog` |
| **收益** | 统一样式 |
| **预计工时** | 1h |

### P6: generic_settings_dialog 改造 (~30min)

| 项目 | 内容 |
|------|------|
| **文件** | `core/generic_settings_dialog.py` |
| **问题** | 函数形式，调用者无法做 pre-show 设置 |
| **方案** | 转换为类继承 `TabbedDialog`，或保持函数但修复 `exec()` 调用模式 |
| **收益** | 统一模式 |
| **预计工时** | 30min |

---

## 三、执行顺序

```
P0 (lan_sharing 去重, -250行)
  → P1 (SettingsDialog 迁移 + make_radio_group)
    → P2 (SidebarSettingsDialog 迁移)
      → P3 (共享按钮样式)
        → P4 (共享齿轮按钮)
          → P5 (TagEditorDialog 改造)
            → P6 (generic_settings_dialog 改造)
```

**总预计工时：5-6 小时**

---

## 四、TabbedDialog 能力清单

### Widget 工厂方法

| 方法 | 用途 |
|------|------|
| `make_label(text, style)` | 创建带样式的 QLabel |
| `make_heading(text)` | 创建标题标签 |
| `make_muted(text)` | 创建灰色标签 |
| `make_input(placeholder)` | 创建 QLineEdit |
| `make_spinbox(min, max, val)` | 创建 QSpinBox |
| `make_checkbox(text, checked)` | 创建 QCheckBox |
| `make_combobox(items)` | 创建 QComboBox |
| `make_primary_btn(text, cb)` | 创建主按钮 |
| `make_secondary_btn(text, cb)` | 创建次按钮 |
| `make_groupbox(title)` | 创建 QGroupBox |
| `make_labeled_row(label, widget)` | 创建标签+控件行 |
| `make_browse_row(label, placeholder)` | 创建浏览文件行 |
| `make_collapsible(title)` | 创建可折叠区域 |
| `_add_tab(widget, label, scrollable)` | 添加标签页 |

### 样式方法

| 方法 | 用途 |
|------|------|
| `_apply_dialog_theme()` | 应用对话框主题 |
| `_groupbox_style()` | GroupBox 样式 |
| `_primary_btn_style()` | 主按钮样式 |
| `_secondary_btn_style()` | 次按钮样式 |

### 主题响应

| 方法 | 用途 |
|------|------|
| `_on_theme_changed()` | 主题变更回调 |
| `_refresh_theme_recursive()` | 递归刷新子控件主题 |

---

## 五、注意事项

1. **内联 CSS 优先**：避免使用 `themes.apply_to(self)`，防止全局样式表冲突
2. **主题切换时子控件刷新**：子控件需实现 `refresh_theme()` 方法
3. **信号连接去重**：检查所有 `bus().theme_changed.connect()` 调用
4. **Unicode 三角箭头**：使用 ▸/▾ 而非 ▶/▼
5. **默认尺寸**：`(360, 520)` 或更小
6. **Widget 工厂一致性**：所有新建对话框应使用 `make_*()` 方法

---

## 六、验收标准

改造完成后的对话框应满足：

1. ✅ 继承 `TabbedDialog` 或使用内联 CSS
2. ✅ 使用 `make_*()` 工厂方法创建控件
3. ✅ 主题切换时所有控件颜色正确更新
4. ✅ 无重复信号连接
5. ✅ 使用 Unicode 三角箭头（▸/▾）而非 Emoji
6. ✅ 默认尺寸合理（360x520 或更小）

---

## 七、执行记录

| 阶段 | 开始时间 | 完成时间 | 备注 |
|------|----------|----------|------|
| P0 | — | — | |
| P1 | — | — | |
| P2 | — | — | |
| P3 | — | — | |
| P4 | — | — | |
| P5 | — | — | |
| P6 | — | — | |
