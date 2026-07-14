# AssetManager UI 模板化设计原则

> 版本：2026-06-08
> 适用范围：所有 Qt 界面组件（Dialog、Panel、MainWindow）

---

## 一、架构概览

### 1.1 三种组件类型

AssetManager 的 UI 组件分为三类，各自使用不同的基类：

| 组件类型 | 基类 | 适用场景 | 文件 |
|---------|------|---------|------|
| **Dialog** | `TabbedDialog` | 设置对话框、多标签页对话框、单页弹窗 | `core/tabbed_dialog.py` |
| **Panel** | `PanelContent` | 侧边栏、信息面板、文件列表 | `panels/base.py` |
| **MainWindow** | `QMainWindow` | 主窗口、启动窗口 | `window.py`, `startup.py` |

**关键原则：** `TabbedDialog` 仅用于 Dialog 类组件，不用于 Panel 或 MainWindow。

### 1.2 文件结构

```
core/
├── tabbed_dialog.py      ← Dialog 模板（400 行）
├── themes.py             ← 主题定义与语义令牌
│
├── settings_dialog.py         ← 继承 TabbedDialog ✅
├── sharing_settings_dialog.py ← 继承 TabbedDialog ✅
├── sidebar_settings_dialog.py ← 有自定义返回值，不迁移
├── tag_editor_dialog.py       ← 含 tag chip，不迁移
└── generic_settings_dialog.py ← 待迁移

panels/
├── base.py               ← PanelContent 基类（手动 QSS）
├── sidebar.py            ← 继承 PanelContent
├── info.py               ← 继承 PanelContent
└── file_list/            ← 继承 PanelContent

window.py                 ← MainWindow（手动 QSS）
startup.py                ← StartupWindow（手动 QSS）
```

---

## 二、TabbedDialog 模板规范

### 2.1 核心原则

| 原则 | 说明 |
|------|------|
| **自包含单文件** | 整个模板系统在一个文件 `core/tabbed_dialog.py` 中 |
| **继承而非组合** | 使用者通过 `class MyDialog(TabbedDialog)` 获得全部能力 |
| **单一 QSS 级联** | 整个对话框只有 `self.setStyleSheet(one_qss_string)` 一次调用 |
| **ObjectName 按钮区分** | 不同类型按钮通过 `objectName` 命名空间区分 |
| **懒连接主题信号** | 主题信号在 `showEvent` 中延迟连接，用 `_theme_connected` 标志确保只连接一次 |

### 2.2 两种使用模式

| 模式 | 覆写方法 | 自动提供的 UI | 适用场景 |
|------|---------|-------------|---------|
| **Tab 模式** | `_setup_tabs()` | QTabWidget + OK/Cancel/Apply 按钮栏 + 主题刷新 | 多分类设置页 |
| **单页模式** | `_build_ui()` | 仅主题刷新（需手动 `setStyleSheet` + 构建 UI） | 弹窗、确认框 |

**检测逻辑：**

```python
if hasattr(self, '_setup_tabs') and type(self)._setup_tabs is not TabbedDialog._setup_tabs:
    self._setup_tabbed_ui()   # Tab 模式
else:
    self._build_ui()           # 单页模式
```

### 2.3 配色约定

**主题色令牌**（全部使用 `themes.get()` 返回的语义色令牌，禁止硬编码颜色值）：

| 令牌 | 用途 | Navy 示例 |
|------|------|-----------|
| `base` | QTabBar::tab 背景、最深层底色 | `#12121a` |
| `panel` | 主背景、输入框背景、滚动条底色 | `#1e1e2a` |
| `header` | 菜单栏、标题栏背景 | `#282840` |
| `accent` | 选中高亮、主按钮、悬停反馈 | `#4a60b0` |
| `heading` | 标题文字、QGroupBox 标题 | `#e0e0f0` |
| `body` | 正文文字 | `#b0b0c8` |
| `muted` | 副标题、占位符 | `#6a6a80` |
| `border` | 边框、分割线 | `#5a5a7a` |
| `success` | 成功状态、连接指示 | `#44c98a` |
| `warning` | 警告状态 | `#f0a040` |
| `danger` | 停止/删除按钮 | `#e05555` |
| `favorite` | 收藏星标 | `#e8c84a` |
| `recent` | 最近访问标记 | `#88aacc` |

**共 13 个语义令牌。**

**透明度约定：** 在 QSS 中使用 Qt 的 hex 透明度语法：`{t['accent']}30` 表示 accent 色 + 30 hex alpha。

### 2.4 Widget 工厂方法

| 方法 | 返回 | ObjectName | 独立 QSS | 说明 |
|------|------|-----------|---------|------|
| `make_label(text)` | QLabel | — | — | 继承全局 |
| `make_heading(text)` | QLabel | — | ✅ | 覆盖 color + font-weight |
| `make_muted(text)` | QLabel | — | ✅ | 覆盖 color + font-size |
| `make_input(ph, txt)` | QLineEdit | — | — | 继承全局 |
| `make_spinbox(min, max, val)` | QSpinBox | — | — | 继承全局 |
| `make_checkbox(text, checked)` | QCheckBox | — | — | 继承全局 |
| `make_combobox(items)` | QComboBox | — | — | 继承全局 |
| `make_groupbox(title)` | QGroupBox | — | — | 继承全局 |
| `make_primary_btn(text, cb)` | QPushButton | `__td_primary_N` | — | ObjectName 区分 |
| `make_secondary_btn(text, cb)` | QPushButton | `__td_secondary_N` | — | ObjectName 区分 |
| `make_gear_btn(cb)` | QPushButton | — | ✅ | 固定尺寸 20×20 flat |
| `make_labeled_row(label, w)` | QHBoxLayout | — | — | 布局 |
| `make_browse_row(label, ph, cb)` | (QHBoxLayout, QLineEdit) | — | — | 布局 |
| `make_collapsible(title)` | (_CollapsibleSection, QVBoxLayout) | — | — | 独立组件 |
| `make_radio_group(title, opts, cur, cb)` | (QGroupBox, QButtonGroup) | — | — | 继承全局 |

**约定：**
1. 工厂方法创建控件后，**不调用** `setStyleSheet()`（除 heading/muted label 和 gear btn）
2. 控件的样式由 Dialog 级的 `_dialog_qss()` 统一提供
3. 需要区分类型的控件使用 `setObjectName()` 打标记，QSS 中用属性选择器匹配
4. 新增工厂方法需在此列表中记录，确保与 QSS 属性选择器一致

### 2.5 QSS 选择器命名

```
QPushButton[objectName^="__td_primary_"]   → accent bg, white text, bold
QPushButton[objectName^="__td_secondary_"] → panel bg, heading text, border
默认 QPushButton                            → accent bg, white text (OK/Cancel in button box)
```

### 2.6 主题刷新机制

```python
# showEvent 中懒连接
def showEvent(self, event):
    super().showEvent(event)
    if not self._theme_connected:
        self._theme_connected = True
        from AssetsManager.core.signal_bus import get as bus
        bus().theme_changed.connect(self._on_theme_changed)

# 主题变更回调
def _on_theme_changed(self, _name):
    self._t = themes.get()
    self.setStyleSheet(self._dialog_qss())  # 重新设置整个 Dialog QSS
    if hasattr(self, '_tabs'):
        self._tabs.setStyleSheet(self._tab_qss())
    for section in self.findChildren(_CollapsibleSection):
        section.refresh_theme()
```

### 2.7 CollapsibleSection 规范

- 使用 Unicode 箭头：▸ (U+25B8) / ▾ (U+25BE)
- 不使用 Emoji 箭头（跨平台兼容性差）
- 折叠区域内容默认隐藏
- 点击头部切换展开/折叠状态
- 主题刷新通过 `refresh_theme()` 方法

---

## 三、内联样式方法规范

### 3.1 适用场景

当子类需要为**不在单一 QSS 级联范围内**的控件设置样式时，使用 TabbedDialog 提供的实例方法：

- **状态切换按钮** — 如 SharingSettingsDialog 的 Start/Stop 按钮
- **状态指示器** — 如服务器连接状态的 QFrame
- **特殊控件** — 需要动态变化样式的组件

### 3.2 TabbedDialog 实例方法

| 方法 | 用途 | 返回 |
|------|------|------|
| `primary_btn_style()` | 主按钮样式 | QSS 字符串 |
| `status_style(active)` | 状态指示器样式 | QSS 字符串 |
| `toggle_btn_style(active)` | 切换按钮样式 | QSS 字符串 |

### 3.3 使用示例

```python
class SharingSettingsDialog(TabbedDialog):
    def _update_status(self):
        running = self._server_status.get("running", False)
        
        # 使用实例方法获取 QSS 字符串
        self._toggle_btn.setStyleSheet(self.toggle_btn_style(running))
        self._status_frame.setStyleSheet(self.status_style(running))
```

### 3.4 设计约束

1. **不创建独立的 `style_helpers.py` 文件** — 避免过度抽象
2. **仅在子类中调用** — 这些方法是 TabbedDialog 的实例方法
3. **返回 QSS 字符串** — 调用者自行决定何时应用
4. **使用 `self._t`** — 主题令牌从实例缓存获取，不调用 `themes.get()`

---

## 四、Panel 基类规范

### 4.1 PanelContent 基类

所有面板继承 `panels/base.py` 的 `PanelContent`：

```python
class PanelContent(QWidget):
    """Base for all panels."""
    
    file_selected = Signal(object)
    directory_selected = Signal(str)
    file_double_clicked = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelContent")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.content_layout = QVBoxLayout(self)
        self._bus_connections: list[tuple[object, str]] = []
```

### 4.2 Panel 主题刷新

Panel 不使用 TabbedDialog 的单一 QSS 级联，而是：

1. **在 `__init__` 中**：使用 `themes.get()` 获取主题令牌
2. **监听主题信号**：通过 `_connect_bus()` 连接 `bus().theme_changed`
3. **在回调中**：重新获取 `themes.get()` 并更新所有样式

```python
class MyPanel(PanelContent):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = themes.get()
        self._setup_ui()
        self._connect_bus(bus().theme_changed, self._refresh_theme)
    
    def _refresh_theme(self, _name):
        self._t = themes.get()
        # 更新所有样式...
```

### 4.3 Panel 信号管理

使用 `_connect_bus()` 追踪信号连接，在 `shutdown()` 中自动断开：

```python
def __init__(self, parent=None):
    super().__init__(parent)
    self._connect_bus(bus().theme_changed, self._refresh_theme)
    self._connect_bus(bus().language_changed, self._refresh_language)

def shutdown(self):
    """Disconnect all tracked bus signals before panel destruction."""
    for signal, slot in self._bus_connections:
        try:
            signal.disconnect(slot)
        except (RuntimeError, TypeError):
            pass
    self._bus_connections.clear()
```

---

## 五、MainWindow 规范

### 5.1 适用场景

当需要以下 QMainWindow 特性时，使用 MainWindow 而非 TabbedDialog：

- 菜单栏（QMenuBar）
- 状态栏（QStatusBar）
- 工具栏（QToolBar）
- 中心 Widget + Dock Widget 布局

### 5.2 主题刷新

MainWindow 使用手动 QSS，需要在主题变更时刷新所有组件：

```python
class MyMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._setup_ui()
        bus().theme_changed.connect(self._refresh_theme)
    
    def _refresh_theme(self, _name):
        t = themes.get()
        
        # 刷新菜单栏
        self._menu_bar.setStyleSheet(self._menu_qss(t))
        
        # 刷新中心 Widget
        self._central.setStyleSheet(f"background: {t['base']};")
        
        # 刷新所有子组件
        for widget in self.findChildren(QWidget):
            if hasattr(widget, 'refresh_theme'):
                widget.refresh_theme()
```

### 5.3 菜单栏样式

```python
def _menu_qss(self, t: dict) -> str:
    return (
        f"QMenuBar {{ background: {t['header']}; color: {t['heading']}; "
        f"border-bottom: 1px solid {t['border']}40; "
        f"padding: 2px 0; font-size: 12px; }}"
        f"QMenuBar::item {{ padding: 4px 10px; border-radius: 4px; }}"
        f"QMenuBar::item:selected {{ background: {t['accent']}50; }}"
        f"QMenu {{ background: {t['panel']}; color: {t['heading']}; "
        f"border: 1px solid {t['border']}; "
        f"border-radius: 6px; padding: 4px; }}"
        f"QMenu::item {{ padding: 5px 28px 5px 12px; border-radius: 4px; }}"
        f"QMenu::item:selected {{ background: {t['accent']}; }}")
```

---

## 六、迁移指南

### 6.1 QDialog → TabbedDialog

**适用条件：**
- 设置类对话框
- 多 Tab 对话框
- 标准 OK/Cancel/Apply 交互模式

**迁移步骤：**

1. 继承 `TabbedDialog`，移除 `themes.apply_to(self)`
2. 将 `QGroupBox + QButtonGroup + QRadioButton` 循环替换为 `self.make_radio_group()`
3. 将内联 `setStyleSheet` 的 QPushButton 替换为 `self.make_primary_btn()` / `self.make_secondary_btn()`
4. 将 QLabel + QSpinBox 手动行替换为 `self.make_labeled_row()`
5. 将手动 QScrollArea + OK 按钮替换为 `_add_tab(widget, label, scrollable=True)` + 内置按钮栏
6. 主题切换验证：切换全部 4 个主题，确认无卡顿、无颜色残留

**示例：**

```python
# 之前
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        themes.apply_to(self)
        layout = QVBoxLayout(self)
        # ... 手动创建所有控件

# 之后
class SettingsDialog(TabbedDialog):
    def __init__(self, parent=None):
        super().__init__(parent, title="Settings")

    def _setup_tabs(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self.make_radio_group("Theme", {...}, current, on_changed))
        self._add_tab(tab, "General", scrollable=True)
```

### 6.2 不适合迁移的场景

| 场景 | 原因 | 建议 |
|------|------|------|
| 需要自定义 `result()` 返回值 | TabbedDialog 使用标准 accept/reject | 保持独立 QDialog |
| 包含特殊自定义组件（如 tag chip） | 改动成本高 | 保持独立 QDialog |
| 单按钮信息弹窗 | 无需模板 | 使用 QMessageBox |
| MainWindow 子类 | 需要菜单栏等特性 | 手动 QSS + `themes.get()` |

---

## 七、最佳实践

### 7.1 主题令牌使用

```python
# ✅ 正确：使用语义令牌
t = themes.get()
f"color: {t['heading']}; background: {t['panel']};"

# ❌ 错误：硬编码颜色值
"color: #e0e0f0; background: #1e1e2a;"
```

### 7.2 透明度语法

```python
# ✅ 正确：使用 Qt hex 透明度
f"background: {t['accent']}30;"  # 30 = 约 19% 不透明度

# ❌ 错误：使用 CSS rgba
f"background: rgba(74, 96, 176, 0.19);"
```

### 7.3 ObjectName 命名

```python
# ✅ 正确：使用命名空间前缀
btn.setObjectName(f"__td_primary_{self._next_id()}")

# ❌ 错误：使用通用名称
btn.setObjectName("primaryButton")
```

### 7.4 信号连接

```python
# ✅ 正确：懒连接 + 标志位
def showEvent(self, event):
    super().showEvent(event)
    if not self._theme_connected:
        self._theme_connected = True
        bus().theme_changed.connect(self._on_theme_changed)

# ❌ 错误：__init__ 中直接连接
def __init__(self):
    super().__init__()
    bus().theme_changed.connect(self._on_theme_changed)  # 可能重复连接
```

### 7.5 CollapsibleSection

```python
# ✅ 正确：使用 Unicode 箭头
arrow = "\u25BE" if self._expanded else "\u25B8"

# ❌ 错误：使用 Emoji 箭头
arrow = "▼" if self._expanded else "▶"
```

---

## 八、验收标准

改造完成后的 UI 组件应满足：

1. ✅ 继承 `TabbedDialog` 或使用手动 QSS + `themes.get()`
2. ✅ 使用 `make_*()` 工厂方法创建控件（Dialog 场景）
3. ✅ 主题切换时所有控件颜色正确更新
4. ✅ 无重复信号连接
5. ✅ 使用 Unicode 三角箭头（▸/▾）而非 Emoji
6. ✅ 默认尺寸合理（Dialog: 360×520 或更小）
7. ✅ 使用语义色令牌，无硬编码颜色值
8. ✅ QSS 使用 hex 透明度语法，不使用 rgba

---

## 九、快速参考

### 9.1 新建 TabbedDialog

```python
# 多 Tab 模式
class MySettings(TabbedDialog):
    def __init__(self, parent=None):
        super().__init__(parent, title="My Settings")

    def _setup_tabs(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self.make_radio_group("Theme", {...}, current, on_changed))
        self._add_tab(tab, "General", scrollable=True)

    def _on_apply(self):
        # save settings
        pass
```

### 9.2 新建单页 Dialog

```python
# 单页模式
class MyPopup(TabbedDialog):
    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.setStyleSheet(self._dialog_qss())
        layout.addWidget(self.make_heading("Confirm?"))
        layout.addWidget(self.make_primary_btn("Yes", self.accept))
```

### 9.3 新建 Panel

```python
# Panel 模式
class MyPanel(PanelContent):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = themes.get()
        self._setup_ui()
        self._connect_bus(bus().theme_changed, self._refresh_theme)
    
    def _setup_ui(self):
        t = self._t
        # ... build UI
    
    def _refresh_theme(self, _name):
        self._t = themes.get()
        # ... update styles
```

### 9.4 新建 MainWindow

```python
# MainWindow 模式
class MyMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._setup_ui()
        bus().theme_changed.connect(self._refresh_theme)
    
    def _setup_ui(self):
        t = themes.get()
        # ... build UI with manual QSS
    
    def _refresh_theme(self, _name):
        t = themes.get()
        # ... update all styles
```
