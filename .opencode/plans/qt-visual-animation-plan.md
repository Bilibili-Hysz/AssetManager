# Qt 桌面应用视觉与动效增强计划

> 创建时间：2026-06-07
> 状态：待执行
> 总任务数：11
> 预计总工时：~7h

---

## 一、现状分析

### 动画基础设施

| 组件 | 动画成熟度 | 机制 | FPS |
|------|-----------|------|-----|
| `_grid_widget.py` | ★★★★★ | QTimer 16ms + opacity dict + 指数衰减 | 60 |
| `_delegate.py` | ★★★★☆ | QTimer 16ms + progress dict + ease_out_cubic | 60 |
| `style.css` (Web UI) | ★★★★☆ | CSS transitions + keyframes + stagger | 60 |
| `themes.py` | ★☆☆☆☆ | 静态 QSS，无动画 | 0 |
| `workspace_bar.py` | ★☆☆☆☆ | 纯 QSS hover | 0 |
| `info.py` | ★☆☆☆☆ | 无动画 | 0 |
| `sidebar.py` | ★★☆☆☆ | Qt 内置树动画 | ~30 |
| `title_bar.py` | ☆☆☆☆☆ | 无动画 | 0 |
| `window.py` | ☆☆☆☆☆ | 无动画 | 0 |

### 设计令牌（Design Tokens）

当前主题系统定义了 12 个语义颜色令牌：

| 令牌 | Navy 值 | 用途 |
|------|---------|------|
| `base` | `#12121a` | QMainWindow, QScrollBar, QScrollArea |
| `panel` | `#1e1e2a` | PanelContent, QListWidget, inputs |
| `header` | `#282840` | Dock title bars, QMenuBar, title bar |
| `border` | `#5a5a7a` | 所有边框，分割线 |
| `heading` | `#e0e0f0` | 粗体文本，选中项 |
| `body` | `#b0b0c8` | 常规文本，标签 |
| `muted` | `#6a6a80` | 副标题，占位符，滚动条 |
| `accent` | `#4a60b0` | 选中、悬停、按钮、徽章 |
| `success` | `#44c98a` | 成功状态 |
| `warning` | `#f0a040` | 警告状态 |
| `danger` | `#e05555` | 错误状态 |

### 硬编码颜色（未主题化）

| 文件 | 行号 | 颜色 | 用途 |
|------|------|------|------|
| `_grid_widget.py` | 543-550 | `#6abf6a`, `#7a9fd4`, `#c480d4`, `#d4a860` | 分类名称颜色 |
| `_delegate.py` | 538-547 | `#2a4a3a`, `#2a2a4a`, `#3a2a3a` 等 | 分类背景色 |
| `_delegate.py` | 560-641 | 各种 hex 值 | 文件类型图标颜色 |
| `_common.py` | 32-39 | `#2f7aa3`, `#3f8c69` 等 | 徽章颜色 |
| `sidebar.py` | 166, 183 | `#e8c84a`, `#88aacc` | 收藏夹/最近头部颜色 |
| `title_bar.py` | 65 | `#c42b1c` | 关闭按钮悬停色 |
| `info.py` | 953-963 | 各种 emoji | 预览提示 |

---

## 二、阶段索引

| 阶段 | 主题 | 任务数 | 预计工时 | 风险 |
|------|------|--------|----------|------|
| **A** | 高影响力视觉改进 | 4 | 3h | 低 |
| **B** | 中等影响力改进 | 4 | 2h | 中 |
| **C** | 低优先级改进 | 3 | 2h | 中 |

### 执行顺序

```
A（高影响力）→ B（中等影响力）→ C（低优先级）
```

---

## 三、阶段详情

### 阶段 A：高影响力视觉改进
> 预计工时：~3h
> 风险：低

#### A-1: Workspace Tab 滑动指示器

**文件**: `widgets/workspace_bar.py`
**行号**: 45-85 (Tab 样式), 125-145 (`_select_tab`)

**当前状态**: Tab 切换时底部边框瞬移（QSS `border-bottom: 2px solid accent`）

**目标**: 200ms 滑动动画，指示器从旧 Tab 位置滑动到新 Tab 位置

**方案**:
1. 创建一个 `QWidget` 作为指示器（2px 高度，accent 背景色）
2. 在 `_select_tab()` 中使用 `QPropertyAnimation` 动画化 `geometry` 属性
3. 持续时间 200ms，缓动曲线 `QEasingCurve.Type.OutCubic`

**关键代码**:
```python
# 创建指示器
self._indicator = QWidget(self)
self._indicator.setFixedHeight(2)
self._indicator.setStyleSheet(f"background: {themes.get()['accent']};")

# 动画
self._indicator_anim = QPropertyAnimation(self._indicator, b"geometry")
self._indicator_anim.setDuration(200)
self._indicator_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

# 在 _select_tab() 中更新位置
def _update_indicator(tab):
    geo = tab.geometry()
    self._indicator_anim.stop()
    self._indicator_anim.setStartValue(self._indicator.geometry())
    self._indicator_anim.setEndValue(QRect(geo.x(), geo.height()-2, geo.width(), 2))
    self._indicator_anim.start()
```

**验证**: 切换 Tab 时指示器平滑滑动

---

#### A-2: Info Panel 预览图交叉淡入

**文件**: `panels/info.py`
**行号**: 610-628 (`_load_preview_pixmap`), 566-569 (空状态)

**当前状态**: 切换文件时预览图瞬移（直接 `setPixmap()`）

**目标**: 旧图淡出(100ms) → 新图淡入(200ms)

**方案**:
1. 在 `update_info()` 中，先启动淡出动画
2. 淡出完成后更新图片，启动淡入动画
3. 使用 `QPropertyAnimation` 动画化 `windowOpacity` 属性

**关键代码**:
```python
def _transition_preview(self, new_pixmap):
    # 淡出
    self._fade_anim = QPropertyAnimation(self._preview_label, b"windowOpacity")
    self._fade_anim.setDuration(100)
    self._fade_anim.setStartValue(1.0)
    self._fade_anim.setEndValue(0.0)
    self._fade_anim.finished.connect(lambda: self._fade_in_preview(new_pixmap))
    self._fade_anim.start()

def _fade_in_preview(self, pixmap):
    self._preview_label.setPixmap(pixmap)
    self._fade_anim.setStartValue(0.0)
    self._fade_anim.setEndValue(1.0)
    self._fade_anim.setDuration(200)
    self._fade_anim.start()
```

**验证**: 切换文件时预览图平滑过渡

---

#### A-3: 标签芯片添加/移除动画

**文件**: `panels/info.py`
**行号**: 638-667 (标签芯片), 669-674 (添加/移除)

**当前状态**: 标签瞬移出现/消失

**目标**: 
- 添加时：scale-in (0→1) + fade-in，150ms
- 移除时：fade-out + scale-out (1→0.8)，100ms

**方案**:
1. 添加标签时，设置初始 `windowOpacity=0` 和 `scale(0.8)`
2. 使用 `QPropertyAnimation` 动画化到正常状态
3. 移除标签时，先启动淡出动画，动画完成后再移除

**关键代码**:
```python
def _animate_tag_add(self, chip):
    chip.setWindowOpacity(0.0)
    anim = QPropertyAnimation(chip, b"windowOpacity")
    anim.setDuration(150)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.start()

def _animate_tag_remove(self, chip, callback):
    anim = QPropertyAnimation(chip, b"windowOpacity")
    anim.setDuration(100)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.finished.connect(callback)
    anim.start()
```

**验证**: 添加/移除标签时有平滑动画

---

#### A-4: Hover 阴影增强

**文件**: `panels/file_list/_delegate.py` (行 278-288), `panels/file_list/_grid_widget.py` (行 234-265)

**当前状态**: hover 阴影是实色矩形偏移 (2px right, 3px down)

**目标**: 3-4 层渐变矩形模拟模糊阴影

**方案**:
```python
# 替换单层阴影为多层渐变
shadows = [
    (1, 1, 15),   # 近层，高透明度
    (2, 2, 10),   # 中层
    (3, 3, 5),    # 远层，低透明度
]
for dx, dy, alpha in shadows:
    shadow_rect = card_rect.adjusted(dx, dy, dx, dy)
    p.fillRect(shadow_rect, QColor(accent_r, accent_g, accent_b, int(alpha * hover_t)))
```

**验证**: hover 时阴影有层次感

---

### 阶段 B：中等影响力改进
> 预计工时：~2h
> 风险：中

#### B-1: 主题切换过渡

**文件**: `core/themes.py`, `window.py`
**行号**: `themes.py:78-173` (QSS), `window.py:240-246` (主题刷新)

**当前状态**: 瞬间替换样式表

**目标**: 300ms 交叉淡入

**方案**:
1. 在切换主题前，截图当前窗口
2. 应用新主题
3. 在截图上叠加新主题，动画化截图的 opacity

**验证**: 切换主题时有平滑过渡

---

#### B-2: Sidebar 搜索结果高亮

**文件**: `panels/sidebar.py`
**行号**: 541-553 (搜索高亮)

**当前状态**: 匹配项前景色变化（accent + bold）

**目标**: 匹配项背景短暂闪烁后渐隐

**方案**:
1. 匹配时设置背景色为 accent at alpha 30
2. 使用 QTimer 启动 500ms 后渐隐动画
3. 渐隐动画 300ms，alpha 从 30 到 0

**验证**: 搜索时匹配项有视觉反馈

---

#### B-3: 空状态改进

**文件**: `panels/file_list/_grid_widget.py` (行 204-209), `panels/info.py` (行 566-569)

**当前状态**: 纯文字 "Folder is empty" / "No file selected"

**目标**: 添加图标 + 更友好的提示文字

**方案**:
```python
# Grid widget 空状态
empty_text = "📭\nThis folder is empty"
empty_sub = "Drop files here or use the upload button"

# Info panel 空状态
empty_text = "👆\nSelect a file to view details"
empty_sub = "Click on any file in the grid"
```

**验证**: 空状态显示友好的提示

---

#### B-4: 硬编码颜色主题化

**文件**: `core/themes.py`, `_common.py`, `_delegate.py`, `_grid_widget.py`, `sidebar.py`, `title_bar.py`

**当前状态**: 分类颜色、状态颜色硬编码

**目标**: 移入 theme dict，支持主题切换

**方案**:
1. 在 `themes.py` 中添加新的颜色令牌：
   - `category_image`, `category_3d`, `category_video`, `category_archive`, `category_document`
   - `sidebar_favorite`, `sidebar_recent`
   - `close_hover`
2. 更新所有使用硬编码颜色的文件

**验证**: 切换主题时所有颜色跟随变化

---

### 阶段 C：低优先级改进
> 预计工时：~2h
> 风险：中

#### C-1: 缩略图加载闪烁

**文件**: `panels/file_list/_grid_widget.py`, `panels/file_list/_delegate.py`

**当前状态**: 加载期间显示空白或类型图标

**目标**: 添加脉冲占位符动画

**方案**:
1. 在缩略图加载期间，显示一个脉冲动画（alpha 在 0.3-0.7 之间循环）
2. 使用 QTimer 驱动，每 100ms 更新一次
3. 缩略图加载完成后，淡入真实图片

**验证**: 加载期间有视觉反馈

---

#### C-2: 启动动画

**文件**: `window.py`

**当前状态**: 窗口瞬间出现

**目标**: 300ms 淡入 + 轻微缩放

**方案**:
```python
def showEvent(self, event):
    super().showEvent(event)
    self.setWindowOpacity(0.0)
    anim = QPropertyAnimation(self, b"windowOpacity")
    anim.setDuration(300)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.start()
```

**验证**: 启动时窗口平滑出现

---

#### C-3: 面板显示/隐藏动画

**文件**: `panels/base.py`

**当前状态**: Dock 面板瞬移出现/消失

**目标**: 200ms 滑入/滑出

**方案**:
1. 面板显示时，从边缘滑入 + 淡入
2. 面板隐藏时，滑出到边缘 + 淡出
3. 使用 `QPropertyAnimation` 动画化 `geometry` 和 `windowOpacity`

**验证**: 面板显示/隐藏时有平滑动画

---

## 四、执行记录

| 阶段 | 开始时间 | 完成时间 | 备注 |
|------|----------|----------|------|
| A | — | — | |
| B | — | — | |
| C | — | — | |

---

## 五、关键设计原则

1. **尊重 reduce_motion**: 所有动画必须检查 `AppSettings("reduce_motion")` 设置
2. **性能优先**: 动画不应影响 UI 响应性，使用 QTimer 而非阻塞
3. **一致性**: 所有动画使用相同的缓动曲线 (OutCubic) 和相似的持续时间
4. **渐进增强**: 动画是增强体验，不是必需功能
5. **测试验证**: 每个动画完成后运行测试确保无回归
